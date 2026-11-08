"""M5 acceptance checks: train a challenger (local runner when VULTR_API_KEY/TRAIN_RUNNER aren't set),
live log, job-token isolation, champion vs challenger on the same holdout, shadow, promote with a
new threshold (scorer reloads live), rollback, roles, the Vultr VM payload, and the Tuning page.
Leaves the original champion in place."""

import os
import sys
import time

import httpx
import psycopg

from zt_core import jobtoken
from zt_core.features import FEATURES
from zt_worker import train_jobs

API = "http://127.0.0.1:8000"
WEB = "http://localhost:3000"
SUPABASE = os.environ["SUPABASE_URL"]
results: list[tuple[bool, str, str]] = []


def check(ok, name, detail=""):
    results.append((bool(ok), name, str(detail)))


def token(role: str) -> dict:
    r = httpx.post(f"{SUPABASE}/auth/v1/token", params={"grant_type": "password"},
                   headers={"apikey": os.environ["PUBLIC_SUPABASE_ANON_KEY"]},
                   json={"email": f"{role}@demo.zentry.local", "password": os.environ["DEMO_PASSWORD"]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def wait_for(conn, sql: str, params, seconds: float):
    end = time.time() + seconds
    while time.time() < end:
        conn.rollback()
        row = conn.execute(sql, params).fetchone()
        if row and row[0]:
            return row
        time.sleep(1)
    return None


def main():
    owner, analyst = token("compliance_manager"), token("analyst")
    api = httpx.Client(base_url=API, timeout=60)
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    original = conn.execute("select id::text from public.model_versions where kind = 'lgbm' and stage = 'champion'").fetchone()[0]

    cfg = api.get("/train/config", headers=owner).json()
    expected = "vultr" if os.environ.get("TRAIN_RUNNER") == "vultr" and os.environ.get("VULTR_API_KEY") else "local"
    check(cfg["runner"] == expected, "runner: local unless TRAIN_RUNNER=vultr and VULTR_API_KEY are set", cfg["runner"])

    r = api.post("/train", headers=analyst, json={"trials": 0})
    check(r.status_code == 403, "analyst cannot start training", f"HTTP {r.status_code}")
    r = api.post("/train", json={"trials": 0})
    check(r.status_code == 401, "anonymous cannot start training", f"HTTP {r.status_code}")
    r = api.post("/train", headers=owner, json={"features": ["side_out", "bogus"], "trials": 0})
    check(r.status_code == 422, "unknown features rejected", f"HTTP {r.status_code}")
    r = api.post("/train", headers=owner, json={"features": ["side_out", "side_out", "hour", "hour"], "trials": 0})
    check(r.status_code == 422, "repeated features count once (2 distinct < 3)", f"HTTP {r.status_code}")
    r = api.post("/train", headers=owner, json={"trials": 16})
    check(r.status_code == 422, "more than 15 Optuna trials rejected", f"HTTP {r.status_code}")

    # a run the worker lost long ago must not block training forever
    stale = conn.execute("""insert into public.train_runs (requested_by, params_json, runner, status, created_at)
                            select id, '{}', 'local', 'running', now() - interval '40 minutes' from auth.users
                            where email = 'compliance_manager@demo.zentry.local' returning id::text""").fetchone()[0]
    conn.commit()

    # every tuning option set, not just the defaults
    chosen = [f for f in FEATURES if f not in ("hour", "kyc_level")]
    r = api.post("/train", headers=owner, json={"features": chosen + ["side_out"], "learning_rate": 0.08,
                                                "num_leaves": 40, "scale_pos_weight": 15, "trials": 2,
                                                "use_analyst_labels": True, "note": "m5 check"})
    run_id = r.json().get("id")
    check(r.status_code == 202 and run_id, "compliance manager starts a run with every option set", run_id)
    st = conn.execute("select status, error from public.train_runs where id = %s", (stale,)).fetchone()
    check(st[0] == "failed" and "abandoned" in (st[1] or ""), "an abandoned run is failed instead of blocking", st[0])
    r2 = api.post("/train", headers=owner, json={"trials": 0})
    check(r2.status_code == 409, "only one run at a time", f"HTTP {r2.status_code}")

    # job token isolation while the run is live
    r = api.get(f"/train/jobs/{run_id}")
    check(r.status_code == 401, "job endpoints need a job token", f"HTTP {r.status_code}")
    r = api.get(f"/train/jobs/{run_id}", headers={"Authorization": f"Bearer {jobtoken.sign('someone-else')}"})
    check(r.status_code == 401, "a token for another run is refused", f"HTTP {r.status_code}")
    r = api.get(f"/train/jobs/{run_id}", headers=owner)
    check(r.status_code == 401, "a user session is not a job token", f"HTTP {r.status_code}")

    t0 = time.time()
    seen_running = wait_for(conn, "select status in ('running', 'succeeded') from public.train_runs where id = %s",
                            (run_id,), 60)
    mid = conn.execute("select length(log_tail) from public.train_runs where id = %s", (run_id,)).fetchone()[0] or 0
    done = wait_for(conn, """select status in ('succeeded', 'failed'), status, model_version_id, log_tail, error
                             from public.train_runs where id = %s""", (run_id,), 900)  # ~10 min on a 4-vCPU VM
    status = done[1] if done else "timeout"
    check(seen_running and status == "succeeded", "run finishes", f"{status} in {time.time() - t0:.0f}s"
          + (f" — {done[4][-200:]}" if done and done[4] else ""))
    if status != "succeeded":
        return report()
    log_tail = done[3]
    check(mid > 0 and all(s in log_tail for s in ("holdout month", "challenger:", "champion", "uploaded model")),
          "live log streamed while running", f"{log_tail.count(chr(10)) + 1} lines")

    mv = conn.execute("""select id::text, stage, artifact_key, card_json, metrics_json from public.model_versions
                         where id = %s""", (done[2],)).fetchone()
    card = mv[3]
    check(mv[1] == "challenger" and mv[2].endswith(f"models/runs/{run_id}.txt"), "registered as challenger", mv[2])
    path = mv[2].removeprefix("local:")
    check(not mv[2].startswith("local:") or os.path.getsize(path) > 10_000, "model artifact stored", path)
    check(card["champion"] and card["champion"]["id"] == original and len(card["curve"]) == len(card["champion"]["curve"]) == 19,
          "champion and challenger evaluated on the same holdout", f"holdout seed {card['holdout']['seed']}, "
          f"PR-AUC {card['champion']['pr_auc']} vs {mv[4]['pr_auc']}")
    check(card["features"] == chosen, "trained on exactly the chosen features", f"{len(card['features'])} features")
    val = next((ln for ln in log_tail.splitlines() if "validation:" in ln), "")
    check(val and not val.rstrip().endswith(" 0 fraud"), "validation split holds fraud rows", val.split("validation:")[-1].strip())
    r = api.post(f"/train/jobs/{run_id}/log", json={"lines": ["late"]},
                 headers={"Authorization": f"Bearer {jobtoken.sign(run_id)}"})
    check(r.status_code == 409, "finished runs accept no more writes", f"HTTP {r.status_code}")

    # dataset the job sees: ids, amounts, times, devices + analyst labels; no names, no ground truth
    r = api.get(f"/train/jobs/{run_id}/dataset", headers={"Authorization": f"Bearer {jobtoken.sign(run_id)}"})
    import gzip, json  # noqa: E401
    body = json.loads(gzip.decompress(r.content))
    check(set(body) == {"accounts", "transactions", "labels"} and len(body["accounts"][0]) == 3
          and len(body["transactions"][0]) == 6, "job dataset has no names or gt_ columns",
          f"{len(body['transactions']):,} txns, {len(body['labels']['fraud'])} analyst-fraud accounts")

    challenger = mv[0]
    since = conn.execute("select max(id) from public.audit_log").fetchone()[0]
    r = api.post(f"/models/{challenger}/stage", headers=owner, json={"stage": "shadow"})
    loaded = wait_for(conn, """select count(*) from public.audit_log where id > %s
                               and action = 'model:loaded_shadow' and object_ref = %s""", (since, f"model:{challenger}"), 30)
    check(r.status_code == 200 and loaded, "shadow mode: scorer loads the shadow model live")

    r = api.post(f"/models/{challenger}/promote", headers=analyst, json={})
    check(r.status_code == 403, "analyst cannot promote", f"HTTP {r.status_code}")
    since = conn.execute("select max(id) from public.audit_log").fetchone()[0]
    r = api.post(f"/models/{challenger}/promote", headers=owner, json={"alert_threshold": 75, "note": "m5 check"})
    champ = conn.execute("""select id::text, params_json->>'alert_threshold' from public.model_versions
                            where kind = 'lgbm' and stage = 'champion'""").fetchone()
    audited = conn.execute("""select count(*) from public.audit_log where id > %s and action = 'model:promote'
                              and actor like 'user:%%'""", (since,)).fetchone()[0]
    check(r.status_code == 200 and champ == (challenger, "75") and audited == 1,
          "promote: challenger becomes champion with threshold 75, audited", champ)
    loaded = wait_for(conn, """select count(*) from public.audit_log where id > %s
                               and action = 'model:loaded_champion' and object_ref = %s""", (since, f"model:{challenger}"), 30)
    check(loaded, "scorer switches to the new champion without a restart")

    since = conn.execute("select max(id) from public.audit_log").fetchone()[0]
    r = api.post("/models/rollback", headers=owner)
    champ = conn.execute("select id::text from public.model_versions where kind = 'lgbm' and stage = 'champion'").fetchone()[0]
    loaded = wait_for(conn, """select count(*) from public.audit_log where id > %s
                               and action = 'model:loaded_champion' and object_ref = %s""", (since, f"model:{original}"), 30)
    check(r.status_code == 200 and champ == original and loaded, "rollback restores the previous champion in one click")

    # Vultr runner payload (no VM is created here)
    script = train_jobs._cloud_init(run_id, "https://api.example.test")
    check(f"TRAIN_RUN_ID={run_id}" in script and "zt_trainer.job" in script and "poweroff" in script
          and not any(s in script for s in ("DATABASE_URL", "SERVICE_ROLE", "VULTR_API_KEY", "S3_SECRET")),
          "Training VM cloud-init: job token only, no DB / Vultr / S3 secrets")
    check(train_jobs.MAX_AGE.total_seconds() == 1800 and train_jobs.TAG == "zentry-train",
          "watchdog deletes zentry-train VMs after 30 minutes")

    with httpx.Client(base_url=WEB, headers={"Origin": WEB}) as web:
        web.post("/login", data={"email": "compliance_manager@demo.zentry.local", "password": os.environ["DEMO_PASSWORD"]})
        r = web.get("/tuning")
        check(r.status_code == 200 and "Champion vs Challenger" in r.text and "Model registry" in r.text,
              "Tuning page renders", f"HTTP {r.status_code}")
    conn.close()
    return report()


def report():
    width = max(len(n) for _, n, _ in results)
    for ok, name, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail[:110]}")
    failed = sum(not ok for ok, _, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
