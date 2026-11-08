"""jobs.train consumer: runs a training job locally (subprocess) or on a Vultr Training VM.

Vultr mode (TRAIN_RUNNER=vultr + VULTR_API_KEY): create an instance tagged `zentry-train` whose
cloud-init clones the repo and runs `zt_trainer.job` with a short-lived job token, wait for the run
to finish, then delete the instance. A watchdog deletes any `zentry-train` instance older than
30 minutes, whatever happened to the run, so a stuck job can't keep billing.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
from datetime import UTC, datetime, timedelta

import httpx
import psycopg

from zt_core import jobtoken
from zt_core.events import EventBus

log = logging.getLogger("zt_worker.train_jobs")

VULTR = "https://api.vultr.com/v2"
TAG = "zentry-train"
MAX_AGE = timedelta(minutes=30)
TERMINAL = ("succeeded", "failed", "cancelled")
REPO = os.environ.get("ZENTRY_GIT_URL", "https://github.com/grapestandards/Vultr_Agent_Rush_Hackathon-zentry")


async def run_trainer_jobs(bus: EventBus, database_url: str) -> None:
    if os.environ.get("VULTR_API_KEY"):
        asyncio.create_task(_watchdog(database_url))
    # Local runs are child processes of this worker, so any still marked running died with the last
    # one. Their jobs.train messages were acked up front and will not come back.
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        cur = await conn.execute("""update public.train_runs set status = 'failed', finished_at = now(),
                                           error = coalesce(error, 'worker restarted during the run; start it again')
                                    where runner = 'local' and status = 'running'""")
        if cur.rowcount:
            log.warning("marked %d interrupted local training run(s) failed", cur.rowcount)
    async for batch in bus.consume("jobs.train", durable="trainer", batch=1):
        for m in batch:
            await m.ack()  # runs take minutes; a crash marks the run failed instead of redelivering
            run_id = m.data["run_id"]
            try:
                async with await psycopg.AsyncConnection.connect(database_url) as conn:
                    row = await (await conn.execute("select runner, status from public.train_runs where id = %s",
                                                    (run_id,))).fetchone()
                if not row or row[1] != "queued":
                    continue
                if row[0] == "vultr":
                    await _run_vultr(database_url, run_id)
                else:
                    await _run_local(database_url, run_id)
            except Exception as e:
                log.exception("training run %s failed", run_id)
                await _fail(database_url, run_id, f"{e.__class__.__name__}: {e}")


async def _note(database_url: str, run_id: str, line: str, **fields) -> None:
    """Append a log line from the worker side (provisioning, VM lifecycle) and update fields."""
    stamp = datetime.now(UTC).strftime("%H:%M:%S")
    sets = "".join(f", {k} = %s" for k in fields)
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        await conn.execute(f"""update public.train_runs set log_tail = right(coalesce(log_tail || E'\\n', '') || %s, 8000)
                               {sets} where id = %s""", [f"[{stamp}] {line}", *fields.values(), run_id])
    log.info("run %s: %s", run_id, line)


async def _fail(database_url: str, run_id: str, error: str) -> None:
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        await conn.execute("""update public.train_runs set status = 'failed', error = coalesce(error, %s),
                              finished_at = coalesce(finished_at, now())
                              where id = %s and status not in ('succeeded', 'failed', 'cancelled')""", (error, run_id))


async def _status(database_url: str, run_id: str) -> str:
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        return (await (await conn.execute("select status from public.train_runs where id = %s", (run_id,))).fetchone())[0]


# ------------------------------------------------------------------ local
async def _run_local(database_url: str, run_id: str) -> None:
    await _note(database_url, run_id, "training on the app server in an isolated process (no database credentials)")
    env = os.environ | {"TRAIN_RUN_ID": run_id, "TRAIN_JOB_TOKEN": jobtoken.sign(run_id),
                        "ZENTRY_API_URL": os.environ.get("ZENTRY_API_URL", "http://127.0.0.1:8000")}
    for secret in ("DATABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "VULTR_API_KEY", "S3_SECRET_KEY", "S3_ACCESS_KEY"):
        env.pop(secret, None)  # the job gets the same (lack of) credentials as on a VM
    proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "zt_trainer.job", env=env)
    try:
        code = await asyncio.wait_for(proc.wait(), MAX_AGE.total_seconds())
    except TimeoutError:
        proc.kill()
        code = -1
    if code != 0:
        await _fail(database_url, run_id, f"trainer exited with {code}")


# ------------------------------------------------------------------ Vultr
def _vultr() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=VULTR, timeout=30,
                             headers={"Authorization": f"Bearer {os.environ['VULTR_API_KEY']}"})


def _cloud_init(run_id: str, api_url: str) -> str:
    ref = os.environ.get("ZENTRY_GIT_REF", "main")
    return f"""#!/bin/bash
# Zentry Training VM: run one training job, then power off (the worker deletes the instance).
set -euxo pipefail
export TRAIN_RUN_ID={run_id} ZENTRY_API_URL={api_url} TRAIN_JOB_TOKEN={jobtoken.sign(run_id)}
export DEBIAN_FRONTEND=noninteractive HOME=/root
apt-get update -q && apt-get install -yq git libgomp1 curl
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone --depth 1 --branch {ref} {REPO} /opt/zentry
cd /opt/zentry && /root/.local/bin/uv run --frozen --package zt-trainer python -m zt_trainer.job || true
poweroff
"""


async def _os_id(http: httpx.AsyncClient) -> int:
    r = await http.get("/os", params={"per_page": 500})
    r.raise_for_status()
    return next(o["id"] for o in r.json()["os"] if o["name"].startswith("Ubuntu 24.04") and o["arch"] == "x64")


async def _run_vultr(database_url: str, run_id: str) -> None:
    api_url = os.environ.get("ZENTRY_PUBLIC_API_URL")
    if not api_url:
        raise RuntimeError("ZENTRY_PUBLIC_API_URL must be set: the Training VM calls the API over the internet/VPC")
    plan = os.environ.get("VULTR_TRAIN_PLAN") or "vc2-2c-4gb"
    region = os.environ.get("VULTR_REGION") or "sgp"
    async with _vultr() as http:
        body = {"region": region, "plan": plan, "label": f"{TAG}-{run_id[:8]}", "tags": [TAG],
                "hostname": f"{TAG}-{run_id[:8]}", "backups": "disabled",
                "user_data": base64.b64encode(_cloud_init(run_id, api_url).encode()).decode()}
        if snap := os.environ.get("VULTR_TRAIN_SNAPSHOT_ID"):
            body["snapshot_id"] = snap
        else:
            body["os_id"] = await _os_id(http)
        if vpc := os.environ.get("VULTR_VPC_ID"):
            body["attach_vpc"] = [vpc]
        await _note(database_url, run_id, f"creating Vultr Training VM ({plan}, {region}) via the Vultr API…",
                    status="provisioning")
        r = await http.post("/instances", json=body)
        r.raise_for_status()
        inst = r.json()["instance"]
        await _note(database_url, run_id, f"instance {inst['id']} created; waiting for cloud-init to start the job",
                    vultr_instance_id=inst["id"])
        try:
            started = datetime.now(UTC)
            ready = False
            while datetime.now(UTC) - started < MAX_AGE:
                await asyncio.sleep(10)
                if not ready:
                    st = (await http.get(f"/instances/{inst['id']}")).json()["instance"]
                    if st["status"] == "active" and st["power_status"] == "running":
                        ready = True
                        await _note(database_url, run_id, f"VM running at {st['main_ip']} — installing trainer…")
                if await _status(database_url, run_id) in TERMINAL:
                    break
            else:
                await _fail(database_url, run_id, "Training VM exceeded 30 minutes")
        finally:
            await http.delete(f"/instances/{inst['id']}")
            await _note(database_url, run_id, f"instance {inst['id']} deleted")


async def _watchdog(database_url: str) -> None:
    """Delete zentry-train instances older than MAX_AGE (or whose run is over), every minute."""
    while True:
        try:
            async with _vultr() as http:
                r = await http.get("/instances", params={"tag": TAG, "per_page": 100})
                r.raise_for_status()
                for inst in r.json()["instances"]:
                    age = datetime.now(UTC) - datetime.fromisoformat(inst["date_created"])
                    if age > MAX_AGE + timedelta(minutes=2):
                        log.warning("watchdog: deleting %s (age %s)", inst["id"], age)
                        await http.delete(f"/instances/{inst['id']}")
                        async with await psycopg.AsyncConnection.connect(database_url) as conn:
                            await conn.execute("""insert into public.audit_log (actor, action, object_ref, after_json)
                                                  values ('service:watchdog', 'vultr:delete_instance', %s, %s)""",
                                               (f"vultr:{inst['id']}", json.dumps({"age_s": int(age.total_seconds())})))
        except Exception:
            log.exception("watchdog pass failed")
        await asyncio.sleep(60)
