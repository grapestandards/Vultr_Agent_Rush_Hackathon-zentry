"""M2 acceptance checks: detection rate on embedded mules, duplicate safety (API + JetStream),
sharding, realtime delivery of new alerts to an analyst session, and the Alert Queue page.
Run after the full feed has been replayed (`make replay`)."""

import asyncio
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psycopg

from zt_core.events import TXN_STREAM, NatsEventBus, shard_of

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"
WEB = "http://localhost:3000"
results: list[tuple[bool, str, str]] = []


def check(ok, name, detail=""):
    results.append((bool(ok), name, str(detail)))


def detection(cur):
    cur.execute("select count(*) from public.sim_feed")
    left = cur.fetchone()[0]
    check(left == 0, "feed fully replayed", f"{left} left in sim_feed")
    cur.execute("select count(*) from public.outbox where published_at is null")
    check(cur.fetchone()[0] == 0, "outbox drained")
    cur.execute("""select count(*), count(*) filter (where exists
                     (select 1 from public.alerts a where a.account_id = x.id))
                   from public.accounts x where x.gt_role = 'mule'""")
    mules, flagged = cur.fetchone()
    rate = flagged / mules if mules else 0
    check(rate >= 0.8, "≥ 80% of embedded mule accounts flagged", f"{flagged}/{mules} = {rate:.1%}")
    cur.execute("""select count(*), count(*) filter (where x.gt_role = 'mule') from public.alerts a
                   join public.accounts x on x.id = a.account_id""")
    total, on_mules = cur.fetchone()
    check(total > 0, "alert precision (informational)", f"{on_mules}/{total} alerts on mule accounts")
    cur.execute("""select count(*) from public.alerts where reason is null or reason = ''
                   or jsonb_array_length(top_features_json) = 0""")
    check(cur.fetchone()[0] == 0, "every alert has a reason + SHAP top features")
    cur.execute("select count(distinct rule) from public.alerts, unnest(rule_hits) rule")
    check(cur.fetchone()[0] >= 2, "rules fire alongside the model", "distinct rules in alerts")


def duplicates(cur, conn):
    cur.execute("select id from public.accounts where gt_role is null and type = 'wallet' order by id limit 2")
    a, b = [r[0] for r in cur.fetchall()]
    tid = f"TXCHECK{uuid.uuid4().hex[:10].upper()}"
    txn = {"id": tid, "from_account": a, "to_account": b, "amount_satang": 12345, "channel": "promptpay",
           "ref_no": f"PPCHECK{tid[-6:]}", "ts": datetime.now(timezone.utc).isoformat(), "device_id": None}
    r1 = httpx.post(f"{API}/ingest/transactions", json={"transactions": [txn]}).json()
    r2 = httpx.post(f"{API}/ingest/transactions", json={"transactions": [txn]}).json()
    check(r1["inserted"] == 1 and r2["duplicates"] == 1, "API ingest: same transaction twice → 1 insert",
          f"{r1} / {r2}")
    cur.execute("select (select count(*) from public.transactions where id = %s),"
                " (select count(*) from public.outbox where msg_id = %s)", (tid, tid))
    check(cur.fetchone() == (1, 1), "one ledger row + one outbox row")
    bad = httpx.post(f"{API}/ingest/transactions", json={"transactions": [{**txn, "id": tid + "F",
                                                                            "amount_satang": 123.45}]})
    check(bad.status_code == 422, "API rejects float money", f"HTTP {bad.status_code}")

    for _ in range(50):  # wait for the relay to publish it
        cur.execute("select published_at is not null from public.outbox where msg_id = %s", (tid,))
        if cur.fetchone()[0]:
            break
        time.sleep(0.2)

    async def nats_dupe():
        bus = await NatsEventBus.connect(os.environ.get("NATS_URL", "nats://127.0.0.1:4222"), "check-m2")
        before = (await bus.js.stream_info(TXN_STREAM)).state.messages
        first = await bus.publish(f"txn.raw.{shard_of(a)}", txn, msg_id=tid)   # relay already sent it
        second = await bus.publish(f"txn.raw.{shard_of(a)}", txn, msg_id=tid)
        after = (await bus.js.stream_info(TXN_STREAM)).state.messages
        info = await bus.js.stream_info("TXN")
        await bus.close()
        return first, second, after - before, info.config.subjects

    first, second, delta, subjects = asyncio.run(nats_dupe())
    check(not first and not second and delta == 0, "JetStream drops re-sent Nats-Msg-Id",
          f"accepted={first},{second} stream +{delta}")
    check("txn.dlq" in subjects, "dead-letter subject configured", subjects)
    return tid


def sharding(cur):
    cur.execute("""select count(distinct subject), count(distinct payload->>'from_account'),
                          count(distinct (payload->>'from_account', subject))
                   from public.outbox where subject like 'txn.raw.%%'""")
    shards, accounts, pairs = cur.fetchone()
    check(shards == 8, "events spread over 8 shards", shards)
    check(accounts == pairs, "each account always maps to one shard", f"{accounts} accounts, {pairs} pairs")


def realtime(conn, tid):
    env = dict(os.environ)
    proc = subprocess.Popen(["node", "scripts/realtime-check.mjs"], cwd=ROOT / "apps/web", env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        lines.append(line.strip())
        if "SUBSCRIBED" in line:
            break
    time.sleep(3)  # SUBSCRIBED arrives before the postgres_changes listener is attached
    with conn.cursor() as cur:
        cur.execute("""insert into public.alerts (transaction_id, account_id, score, priority, reason, txn_ts)
                       select id, to_account, 99, 1, 'realtime check', ts from public.transactions where id = %s
                       returning id""", (tid,))
        alert_id = cur.fetchone()[0]
    conn.commit()
    out, _ = proc.communicate(timeout=25)
    lines += out.split()
    check(proc.returncode == 0 and str(alert_id) in " ".join(lines), "analyst receives new alert via Realtime",
          " ".join(lines)[-80:])
    with conn.cursor() as cur:
        cur.execute("delete from public.alerts where id = %s", (alert_id,))
    conn.commit()


def page():
    with httpx.Client(base_url=WEB, headers={"Origin": WEB}) as http:
        http.post("/login", data={"email": "analyst@demo.zentry.local", "password": os.environ["DEMO_PASSWORD"]})
        r = http.get("/alerts")
        cards = r.text.count("rounded-2xl bg-white p-4")
        check(r.status_code == 200 and "waiting for review" in r.text and cards > 0,
              "Alert Queue renders alerts for analyst", f"HTTP {r.status_code}, {cards} alert cards")


def cleanup(conn, tid):
    with conn.cursor() as cur:
        cur.execute("delete from public.alerts where transaction_id = %s", (tid,))
        cur.execute("delete from public.outbox where msg_id = %s", (tid,))
        cur.execute("delete from public.transactions where id = %s", (tid,))
    conn.commit()


def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        detection(cur)
        sharding(cur)
        conn.commit()
        tid = duplicates(cur, conn)
        conn.commit()
        try:
            realtime(conn, tid)
            page()
        finally:
            cleanup(conn, tid)
    width = max(len(n) for _, n, _ in results)
    for ok, name, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = sum(not ok for ok, _, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
