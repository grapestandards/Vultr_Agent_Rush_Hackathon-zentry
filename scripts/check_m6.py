"""M6 acceptance checks: reconciliation catches every injected break (and nothing else), the agent's
journal entries balance, uploads replace their file, confirming a break opens a follow-up, the
follow-up agent drafts → human approves → reply sets a promise date, a late settlement auto-closes
its follow-up, and closing a mule case as fraud opens victim-refund follow-ups."""

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import httpx
import psycopg

API = "http://127.0.0.1:8000"
WEB = "http://localhost:3000"
SUPABASE = os.environ["SUPABASE_URL"]
RAW = Path("data/generated")
LATE_FILE = "check-m6-late.csv"
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


def run_recon(api, headers, conn, body=None) -> tuple[str, dict]:
    r = api.post("/recon/runs", headers=headers, json=body or {})
    run_id = r.json().get("id") if r.status_code == 202 else None
    if not run_id:
        return "", {"error": r.text}
    row = wait_for(conn, "select status in ('review', 'done', 'failed'), status, stats_json from public.recon_runs where id = %s",
                   (run_id,), 120)
    return run_id, (row[2] | {"status": row[1]}) if row else {"status": "timeout"}


def cleanup(conn, reset_recon=False):
    conn.rollback()
    if reset_recon:  # the check owns recon state: start from no runs, decisions or recon follow-ups
        conn.execute("delete from public.follow_ups where kind = 'recon'")
        conn.execute("delete from public.recon_runs")
    conn.execute("""delete from public.recon_matches where settlement_id in
                    (select id from public.settlements where raw_file_key = %s)""", (f"settlements/bank/{LATE_FILE}",))
    conn.execute("delete from public.settlements where raw_file_key = %s", (f"settlements/bank/{LATE_FILE}",))
    conn.commit()


def main():
    fin, coll, analyst = token("finance_ops"), token("collections"), token("analyst")
    api = httpx.Client(base_url=API, timeout=60)
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cleanup(conn, reset_recon=True)
    manifest = json.loads((RAW / "manifest.json").read_text())

    check(api.post("/recon/runs", headers=analyst, json={}).status_code == 403, "analyst cannot run reconciliation")
    run_id, stats = run_recon(api, fin, conn)
    check(stats.get("status") == "review", "finance ops runs reconciliation (3 passes + agent)", stats.get("status"))

    # ---- every injected break, nothing else
    expected = set()
    for b in manifest["breaks"]:
        if b["type"] == "missing_in_bank":
            tx = conn.execute("select id from public.transactions where ref_no = %s", (b["ref_no"],)).fetchone()
            expected.add((b["type"], tx[0] if tx else b["ref_no"]))
        else:
            expected.add((b["type"], b["settlement_id"]))
    found = {(t, s or tx) for t, s, tx in conn.execute("""select break_type, settlement_id, transaction_id
             from public.recon_matches where run_id = %s and break_type is not null""", (run_id,))}
    check(expected <= found, "every injected break is caught", f"{len(expected & found)}/{len(expected)}")
    check(found <= expected, "no false breaks", f"{len(found - expected)} extra: {sorted(found - expected)[:3]}")
    check(all(v == 10 for v in stats.get("by_break", {}).values()) and len(stats.get("by_break", {})) == 6,
          "6 break types × 10", stats.get("by_break"))
    check(stats.get("match_rate", 0) > 0.99 and set(stats.get("by_rule", {})) >= {"ref_exact", "many_to_one"},
          "auto-match rate > 99%", f"{stats.get('match_rate')} {stats.get('by_rule')}")

    rows = conn.execute("""select break_type, explanation, journal_json, follow_up_json from public.recon_matches
                           where run_id = %s and break_type is not null""", (run_id,)).fetchall()
    balanced = all(j and sum(l["debit_satang"] for l in j["lines"]) == sum(l["credit_satang"] for l in j["lines"]) > 0
                   for _, _, j, _ in rows)
    check(all(e for _, e, _, _ in rows) and balanced, "every break has an explanation and a balanced journal entry")
    check(all(("TX" in e or "PP" in e or "GW" in e or "ST" in e) for _, e, _, _ in rows),
          "explanations cite the references they are about")
    owed = {t for t, _, _, f in rows if f}
    check(owed <= {"fee", "amount_mismatch", "missing_in_bank"} and {"fee", "missing_in_bank"} <= owed,
          "follow-ups suggested only for money owed to us", sorted(owed))

    # ---- upload
    r = api.post("/recon/upload", headers=fin, json={"source": "bank", "filename": "x.csv", "content": "a,b\n1,2", "run": False})
    check(r.status_code == 422, "malformed CSV is rejected", f"HTTP {r.status_code}")
    sample = sorted((RAW / "raw/settlements/bank").glob("*.csv"))[3]
    r = api.post("/recon/upload", headers=fin, json={"source": "bank", "filename": sample.name,
                                                     "content": sample.read_text(), "run": False})
    n_file = conn.execute("select count(*) from public.settlements where raw_file_key = %s",
                          (f"settlements/bank/{sample.name}",)).fetchone()[0]
    check(r.status_code == 202 and n_file == len(sample.read_text().splitlines()) - 1,
          "re-uploading a statement file keeps one copy of its rows", f"{n_file} rows, stored {r.json().get('stored')}")

    # ---- confirm → follow-up → agent draft → approval → reply → promise
    fee = conn.execute("""select id from public.recon_matches where run_id = %s and break_type = 'missing_in_bank'
                          order by id limit 1""", (run_id,)).fetchone()[0]
    check(api.post(f"/recon/breaks/{fee}/resolve", headers=coll, json={"action": "confirm"}).status_code == 403,
          "collections cannot post journal entries")
    r = api.post(f"/recon/breaks/{fee}/resolve", headers=fin, json={"action": "confirm", "note": "m6 check"})
    fu = r.json().get("follow_up_id")
    check(r.status_code == 200 and fu, "confirming a missing-in-bank break opens a follow-up", fu)
    check(api.post(f"/recon/breaks/{fee}/resolve", headers=fin, json={"action": "dismiss"}).status_code == 409,
          "a break is decided once")
    draft = wait_for(conn, """select id::text, level, draft, author from public.messages
                              where follow_up_id = %s and status = 'draft'""", (fu,), 70)
    check(draft and draft[1] == 1 and "฿" in draft[2] and "เรียน" in draft[2] and "Dear" in draft[2],
          "agent drafts a level-1 reminder in Thai + English", draft and draft[3])
    r = api.post(f"/messages/{draft[0]}/approve", headers=analyst, json={})
    check(r.status_code == 403, "analyst cannot approve outbound messages", f"HTTP {r.status_code}")
    r = api.post(f"/messages/{draft[0]}/approve", headers=coll, json={"body": draft[2] + "\n(edited)"})
    st = conn.execute("""select f.stage, m.status, m.draft like '%%(edited)', m.approved_by is not null
                         from public.follow_ups f join public.messages m on m.follow_up_id = f.id where m.id = %s""",
                      (draft[0],)).fetchone()
    check(r.status_code == 200 and st == ("reminded", "sent", True, True), "human approves (with edits) → sent, stage reminded", st)
    api.post(f"/followups/{fu}/reply", headers=coll, json={"text": "ได้รับแล้วครับ จะโอนให้วันศุกร์นี้"})
    p = wait_for(conn, "select promise_date, stage from public.follow_ups where id = %s and stage = 'promised'", (fu,), 20)
    check(p and p[0].weekday() == 4 and p[0] >= date.today(), "reply “จะโอนให้วันศุกร์นี้” → promised for Friday", p and p[0])
    audited = conn.execute("""select count(distinct action) from public.audit_log where object_ref in (%s, %s)
                              and action in ('followup:draft', 'message:approve_send', 'followup:read_reply')""",
                           (f"follow_up:{fu}", f"message:{draft[0]}")).fetchone()[0]
    check(audited == 3, "draft, approval and reply reading are audited", audited)

    dup = conn.execute("""select id, settlement_id from public.recon_matches where run_id = %s and break_type = 'duplicate'
                          order by id limit 1""", (run_id,)).fetchone()
    api.post(f"/recon/breaks/{dup[0]}/resolve", headers=fin, json={"action": "dismiss", "note": "m6 check"})

    # ---- the money arrives: a late bank credit clears the break and closes the follow-up
    ref, amount = conn.execute("""select t.ref_no, t.amount_satang from public.recon_matches m
                                  join public.transactions t on t.id = m.transaction_id where m.id = %s""", (fee,)).fetchone()
    payer = conn.execute("""select c.name_en from public.transactions t join public.accounts a on a.id = t.from_account
                            join public.customers c on c.id = a.customer_id where t.ref_no = %s""", (ref,)).fetchone()[0]
    day = conn.execute("""select (ts at time zone 'Asia/Bangkok')::date from public.transactions where ref_no = %s""",
                       (ref,)).fetchone()[0]
    csv_text = f"ref_no,counterparty_name,amount_thb,fee_thb,value_date\n{ref},{payer},{amount / 100:.2f},0.00,{day}\n"
    api.post("/recon/upload", headers=fin, json={"source": "bank", "filename": LATE_FILE, "content": csv_text, "run": False})
    run2, stats2 = run_recon(api, fin, conn)
    closed = conn.execute("select stage, closed_reason from public.follow_ups where id = %s", (fu,)).fetchone()
    check(closed == ("closed", "cleared in reconciliation") and stats2.get("breaks") == 59,
          "late settlement clears the break and auto-closes its follow-up", f"{closed} · {stats2.get('breaks')} breaks")
    carried = conn.execute("""select resolution from public.recon_matches where run_id = %s and settlement_id = %s
                              and break_type = 'duplicate'""", (run2, dup[1])).fetchone()
    check(carried == ("dismissed",), "earlier decisions carry over to the new run", carried)
    cleanup(conn)

    # ---- mule case closed as fraud → victim refund follow-ups
    case_id = conn.execute("""select c.id::text from public.cases c join public.case_links l on l.case_id = c.id
                              join public.alerts a on a.id = l.alert_id where c.type = 'mule'
                              group by c.id order by max(a.score) desc, count(*) desc limit 1""").fetchone()[0]
    r = api.post(f"/cases/{case_id}/decision", headers=analyst, json={"decision": "close_fraud", "note": "m6 check"})
    refunds = conn.execute("""select count(*), coalesce(sum(amount_due_satang), 0) from public.follow_ups
                              where case_id = %s and kind = 'victim_refund'""", (case_id,)).fetchone()
    check(r.status_code == 200 and refunds[0] > 0 and refunds[1] > 0,
          "closing a mule case as fraud opens victim-refund follow-ups (traced held funds)",
          f"{refunds[0]} victims, ฿{refunds[1] / 100:,.0f} held")

    # ---- PII masking + audited reveal
    rest = {"apikey": os.environ["PUBLIC_SUPABASE_ANON_KEY"], **analyst}
    r_full = httpx.get(f"{SUPABASE}/rest/v1/customers", params={"select": "name_en", "limit": 1}, headers=rest)
    r_mask = httpx.get(f"{SUPABASE}/rest/v1/customers", params={"select": "display_en", "limit": 1}, headers=rest)
    check(r_full.status_code in (401, 403) and r_mask.status_code == 200 and r_mask.json()[0]["display_en"].endswith("****"),
          "browsers cannot read full names, only masked ones", f"{r_full.status_code} / {r_mask.json()[0]['display_en']}")
    net = api.get("/graph/network", params={"case": case_id}, headers=analyst).json()
    people = [n for n in net["nodes"] if n["type"] != "merchant"]
    merchants = [n for n in net["nodes"] if n["type"] == "merchant"]
    check(people and all(n["name"].endswith("****") for n in people)
          and all(not n["name"].endswith("****") for n in merchants),
          "graph masks people, keeps merchant names", people[0]["name"] if people else "")
    acct = people[0]["id"]
    ent = api.get(f"/accounts/{acct}/entity", headers=fin)
    check(ent.status_code == 200 and ent.json()["profile"]["name"].endswith("****") and ent.json()["history"],
          "entity page: masked profile, balance history, counterparties", f"{ent.json()['stats']['transfers']} transfers")
    check(api.post("/pii/reveal", headers=fin, json={"account_id": acct, "reason": "curious"}).status_code == 403,
          "finance ops cannot reveal names")
    check(api.post("/pii/reveal", headers=analyst, json={"account_id": acct, "reason": ""}).status_code == 422,
          "a reveal needs a reason")
    since = conn.execute("select max(id) from public.audit_log").fetchone()[0]
    r = api.post("/pii/reveal", headers=analyst, json={"account_id": acct, "reason": "m6 check: STR draft"})
    logged = conn.execute("""select count(*) from public.audit_log where id > %s and action = 'pii:reveal'
                             and object_ref = %s and after_json->>'reason' = 'm6 check: STR draft'""", (since, f"account:{acct}")).fetchone()[0]
    check(r.status_code == 200 and not r.json()["name_en"].endswith("****") and logged == 1,
          "analyst reveal returns the full name and is audited with the reason")

    with httpx.Client(base_url=WEB, headers={"Origin": WEB}) as web:
        web.post("/login", data={"email": "finance_ops@demo.zentry.local", "password": os.environ["DEMO_PASSWORD"]})
        r = web.get("/recon")
        check(r.status_code == 200 and "Reconciliation" in r.text and "Missing in bank" in r.text, "Reconciliation page renders")
    with httpx.Client(base_url=WEB, headers={"Origin": WEB}) as web:
        web.post("/login", data={"email": "collections@demo.zentry.local", "password": os.environ["DEMO_PASSWORD"]})
        r = web.get("/follow-ups")
        check(r.status_code == 200 and "Payment Follow-ups" in r.text and "Victim refund" in r.text, "Follow-ups page renders")
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
