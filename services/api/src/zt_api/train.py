"""Model tuning (W4): start training runs, serve the training job, and move models between stages.

Two audiences: the web app (Supabase JWT; compliance managers start runs and promote) and the
training job itself (short-lived job token from zt_core.jobtoken; no DB or storage credentials)."""

from __future__ import annotations

import gzip
import json
import os
from datetime import datetime
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from psycopg.rows import dict_row, tuple_row
from pydantic import BaseModel, Field

from zt_core import jobtoken, storage
from zt_core.features import FEATURES
from zt_core.settings import env

from .auth import User, current_user, require

router = APIRouter(tags=["tuning"])

LOG_TAIL_CHARS = 8000
OWNERS = ("compliance_manager",)  # the model owner role; admin always passes


def _connect():
    return psycopg.connect(env("DATABASE_URL"), row_factory=dict_row)


def runner() -> Literal["local", "vultr"]:
    return "vultr" if os.environ.get("TRAIN_RUNNER") == "vultr" and os.environ.get("VULTR_API_KEY") else "local"


# ------------------------------------------------------------------ web app
class TrainIn(BaseModel):
    features: list[str] = Field(default_factory=lambda: list(FEATURES))
    learning_rate: float | None = Field(default=None, gt=0, le=1)
    num_leaves: int | None = Field(default=None, ge=4, le=512)
    min_data_in_leaf: int | None = Field(default=None, ge=1, le=2000)
    scale_pos_weight: float | None = Field(default=None, gt=0, le=200)
    # each trial is a full 300-round fit (up to ~30 s on the 4-vCPU VM); 15 keeps a run well inside the
    # worker's 30-minute limit
    trials: int = Field(default=0, ge=0, le=15, description="Optuna trials; 0 = use the given params")
    use_analyst_labels: bool = True
    note: str = Field(default="", max_length=500)


@router.get("/train/config")
def train_config(user: User = Depends(current_user)) -> dict:
    """Where the next run will execute, for the Tuning page."""
    require(user, "analyst", *OWNERS)
    return {"runner": runner(), "object_storage": storage.s3_enabled(), "features": FEATURES,
            "plan": os.environ.get("VULTR_TRAIN_PLAN") or "vc2-2c-4gb", "region": os.environ.get("VULTR_REGION") or "sgp"}


@router.post("/train", status_code=202)
async def start_training(body: TrainIn, request: Request, user: User = Depends(current_user)) -> dict:
    require(user, *OWNERS)
    body.features = list(dict.fromkeys(body.features))  # LightGBM rejects repeated feature names
    unknown = set(body.features) - set(FEATURES)
    if unknown or len(body.features) < 3:
        raise HTTPException(422, f"choose at least 3 known features (unknown: {sorted(unknown)})")
    how = runner()
    with _connect() as conn:
        # a run the worker lost (restarted mid-run) would otherwise block training forever; the worker
        # kills its own runs at 30 minutes, so anything older is dead
        conn.execute("""update public.train_runs set status = 'failed', finished_at = now(),
                               error = coalesce(error, 'abandoned: no progress within 35 minutes')
                        where status in ('queued', 'provisioning', 'running')
                          and created_at < now() - interval '35 minutes'""")
        busy = conn.execute("""select count(*) n from public.train_runs
                               where status in ('queued', 'provisioning', 'running')""").fetchone()["n"]
        if busy:
            raise HTTPException(409, "a training run is already in progress")
        run = conn.execute("""insert into public.train_runs (requested_by, params_json, runner)
                              values (%s, %s, %s) returning id, status, runner, created_at""",
                           (user.id, json.dumps(body.model_dump()), how)).fetchone()
        conn.execute("insert into public.audit_log (actor, action, object_ref, after_json) values (%s, 'train:start', %s, %s)",
                     (user.actor, f"train_run:{run['id']}", json.dumps(body.model_dump())))
    await request.app.state.bus.publish("jobs.train", {"run_id": str(run["id"])}, msg_id=f"train:{run['id']}")
    return run


class StageIn(BaseModel):
    stage: Literal["shadow", "challenger"]


@router.post("/models/{model_id}/stage")
def set_stage(model_id: str, body: StageIn, user: User = Depends(current_user)) -> dict:
    """Shadow mode: the scorer also scores with this model but never raises alerts from it."""
    require(user, *OWNERS)
    with _connect() as conn, conn.transaction():
        m = conn.execute("select stage from public.model_versions where id = %s for update", (model_id,)).fetchone()
        if not m or m["stage"] not in ("challenger", "shadow"):
            raise HTTPException(409, "only challenger / shadow models can change this way")
        if body.stage == "shadow":
            conn.execute("update public.model_versions set stage = 'challenger' where kind = 'lgbm' and stage = 'shadow'")
        conn.execute("update public.model_versions set stage = %s, shadow_json = null where id = %s", (body.stage, model_id))
        _audit(conn, user, f"model:{body.stage}", model_id, {"stage": m["stage"]}, {"stage": body.stage})
    return {"id": model_id, "stage": body.stage}


class PromoteIn(BaseModel):
    alert_threshold: int | None = Field(default=None, ge=30, le=99, description="score needed to alert")
    note: str = Field(default="", max_length=500)


@router.post("/models/{model_id}/promote")
def promote(model_id: str, body: PromoteIn, user: User = Depends(current_user)) -> dict:
    """Human approval step: the challenger replaces the champion; the scorer picks it up live."""
    require(user, *OWNERS)
    with _connect() as conn, conn.transaction():
        m = conn.execute("""select id, stage, params_json, artifact_key from public.model_versions
                            where id = %s and kind = 'lgbm' for update""", (model_id,)).fetchone()
        if not m or m["stage"] == "champion":
            raise HTTPException(409, "model not found or already champion")
        old = conn.execute("""update public.model_versions set stage = 'retired'
                              where kind = 'lgbm' and stage = 'champion' returning id""").fetchone()
        params = m["params_json"] | ({"alert_threshold": body.alert_threshold} if body.alert_threshold else {})
        conn.execute("""update public.model_versions set stage = 'champion', promoted_at = now(), promoted_by = %s,
                        params_json = %s where id = %s""", (user.id, json.dumps(params), model_id))
        _audit(conn, user, "model:promote", model_id, {"champion": old and str(old["id"])},
               {"champion": model_id, "alert_threshold": params.get("alert_threshold"), "note": body.note})
    return {"champion": model_id, "previous": old and str(old["id"])}


@router.post("/models/rollback")
def rollback(user: User = Depends(current_user)) -> dict:
    """One click back to the previously promoted model."""
    require(user, *OWNERS)
    with _connect() as conn, conn.transaction():
        cur = conn.execute("""select id from public.model_versions where kind = 'lgbm' and stage = 'champion'
                              for update""").fetchone()
        prev = conn.execute("""select id from public.model_versions where kind = 'lgbm' and stage = 'retired'
                               and promoted_at is not null order by promoted_at desc limit 1""").fetchone()
        if not cur or not prev:
            raise HTTPException(409, "no earlier champion to roll back to")
        conn.execute("update public.model_versions set stage = 'challenger' where id = %s", (cur["id"],))
        conn.execute("update public.model_versions set stage = 'champion', promoted_at = now(), promoted_by = %s where id = %s",
                     (user.id, prev["id"]))
        _audit(conn, user, "model:rollback", str(prev["id"]), {"champion": str(cur["id"])}, {"champion": str(prev["id"])})
    return {"champion": str(prev["id"]), "previous": str(cur["id"])}


def _audit(conn, user: User, action: str, model_id: str, before: dict, after: dict) -> None:
    conn.execute("""insert into public.audit_log (actor, action, object_ref, before_json, after_json)
                    values (%s, %s, %s, %s, %s)""",
                 (user.actor, action, f"model:{model_id}", json.dumps(before), json.dumps(after)))


# ------------------------------------------------------------------ training job
def job_run(run_id: str, authorization: str, writable: bool = True) -> dict:
    if not jobtoken.verify(authorization.removeprefix("Bearer ").strip(), run_id):
        raise HTTPException(401, "invalid or expired job token")
    with _connect() as conn:
        run = conn.execute("select * from public.train_runs where id = %s", (run_id,)).fetchone()
    if not run:
        raise HTTPException(404, "run not found")
    if writable and run["status"] not in ("queued", "provisioning", "running"):
        raise HTTPException(409, f"run is {run['status']}")
    return run


def _champion(conn) -> dict | None:
    return conn.execute("""select id::text, name, artifact_key from public.model_versions
                           where kind = 'lgbm' and stage = 'champion'""").fetchone()


@router.get("/train/jobs/{run_id}")
def job_spec(run_id: str, authorization: str = Header(default="")) -> dict:
    run = job_run(run_id, authorization)
    key = f"models/runs/{run_id}.txt"
    if storage.s3_enabled():
        upload = {"url": storage.presign(key), "artifact_key": f"s3:{key}"}
    else:
        upload = {"url": f"{os.environ.get('ZENTRY_API_URL', 'http://api:8000')}/train/jobs/{run_id}/artifact",
                  "headers": {"Authorization": authorization}, "artifact_key": f"local:{key}"}
    with _connect() as conn:
        conn.execute("""update public.train_runs set status = 'running', started_at = coalesce(started_at, now())
                        where id = %s""", (run_id,))
        champion = _champion(conn)
    return {"run_id": run_id, "runner": run["runner"], "params": run["params_json"], "upload": upload,
            "champion": champion and {"id": champion["id"], "name": champion["name"]}}


@router.get("/train/jobs/{run_id}/champion")
def job_champion(run_id: str, authorization: str = Header(default="")) -> Response:
    job_run(run_id, authorization, writable=False)
    with _connect() as conn:
        champion = _champion(conn)
    if not champion:
        raise HTTPException(404, "no champion")
    return Response(storage.fetch(champion["artifact_key"]).read_bytes(), media_type="text/plain")


@router.get("/train/jobs/{run_id}/dataset")
def job_dataset(run_id: str, authorization: str = Header(default="")) -> Response:
    """The live month plus analyst labels. No names, no ground truth: ids, amounts, times, devices."""
    job_run(run_id, authorization, writable=False)
    with _connect() as conn, conn.cursor(row_factory=tuple_row) as cur:
        accounts = [[a, o.isoformat(), k] for a, o, k in cur.execute(
            "select a.id, a.opened_at, c.kyc_level from public.accounts a join public.customers c on c.id = a.customer_id")]
        txns = [[i, f, t, amt, ts.isoformat(), d] for i, f, t, amt, ts, d in cur.execute(
            "select id, from_account, to_account, amount_satang, ts, device_id from public.transactions order by ts, id")]
        decided = cur.execute("""
            with w as (select c.id, c.disposition, min(al.txn_ts) lo, max(al.txn_ts) hi
                       from public.cases c join public.case_links l on l.case_id = c.id
                       join public.alerts al on al.id = l.alert_id
                       where c.disposition in ('fraud', 'false_positive') group by 1, 2)
            select l.account_id, w.disposition, w.lo - interval '48 hours', w.hi + interval '48 hours'
            from w join public.case_links l on l.case_id = w.id where l.account_id is not null""").fetchall()
        alerted = {r[0] for r in cur.execute("select distinct account_id from public.alerts")}
    fraud = {a: [lo.isoformat(), hi.isoformat()] for a, d, lo, hi in decided if d == "fraud"}
    clean = sorted({a for a, d, _, _ in decided if d == "false_positive"} - set(fraud))
    body = {"accounts": accounts, "transactions": txns,
            "labels": {"fraud": fraud, "false_positive": clean, "undecided": sorted(alerted - set(fraud) - set(clean))}}
    return Response(gzip.compress(json.dumps(body).encode(), 5), media_type="application/gzip")


class LogIn(BaseModel):
    lines: list[str] = Field(max_length=200)


@router.post("/train/jobs/{run_id}/log", status_code=204)
async def job_log(run_id: str, body: LogIn, request: Request, authorization: str = Header(default="")) -> None:
    job_run(run_id, authorization)
    text = "\n".join(line[:500] for line in body.lines)
    with _connect() as conn:
        conn.execute("""update public.train_runs
                        set log_tail = right(coalesce(log_tail || E'\\n', '') || %s, %s) where id = %s""",
                     (text, LOG_TAIL_CHARS, run_id))
    await request.app.state.bus.publish(f"train.logs.{run_id}", {"lines": body.lines})


@router.put("/train/jobs/{run_id}/artifact", status_code=204)
async def job_artifact(run_id: str, request: Request, authorization: str = Header(default="")) -> None:
    """Local mode only; with Object Storage the job uploads to a pre-signed URL instead."""
    job_run(run_id, authorization)
    body = await request.body()
    if not body.startswith(b"tree") or len(body) > 50_000_000:
        raise HTTPException(422, "not a LightGBM model file")
    path = storage.model_root() / "models" / "runs" / f"{run_id}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


class CompleteIn(BaseModel):
    metrics: dict
    card: dict
    artifact_key: str


@router.post("/train/jobs/{run_id}/complete")
def job_complete(run_id: str, body: CompleteIn, authorization: str = Header(default="")) -> dict:
    run = job_run(run_id, authorization)
    if body.artifact_key not in (f"local:models/runs/{run_id}.txt", f"s3:models/runs/{run_id}.txt"):
        raise HTTPException(422, "unexpected artifact key")
    name = f"lgbm-{datetime.now():%m%d-%H%M}"
    params = {"features": body.card.get("features", FEATURES), **body.card.get("params", {})}
    with _connect() as conn, conn.transaction():
        mv = conn.execute("""insert into public.model_versions (kind, name, params_json, metrics_json, card_json,
                                 artifact_key, stage, train_run_id)
                             values ('lgbm', %s, %s, %s, %s, %s, 'challenger', %s) returning id""",
                          (name, json.dumps(params), json.dumps(body.metrics), json.dumps(body.card),
                           body.artifact_key, run_id)).fetchone()
        conn.execute("""update public.train_runs set status = 'succeeded', model_version_id = %s, finished_at = now()
                        where id = %s""", (mv["id"], run_id))
        conn.execute("""insert into public.audit_log (actor, action, object_ref, after_json)
                        values (%s, 'train:complete', %s, %s)""",
                     (f"job:{run['runner']}", f"model:{mv['id']}", json.dumps(body.metrics)))
    return {"model_version_id": str(mv["id"]), "name": name}


class FailIn(BaseModel):
    error: str = Field(max_length=4000)


@router.post("/train/jobs/{run_id}/fail", status_code=204)
def job_fail(run_id: str, body: FailIn, authorization: str = Header(default="")) -> None:
    job_run(run_id, authorization)
    with _connect() as conn:
        conn.execute("""update public.train_runs set status = 'failed', error = %s, finished_at = now()
                        where id = %s""", (body.error, run_id))
