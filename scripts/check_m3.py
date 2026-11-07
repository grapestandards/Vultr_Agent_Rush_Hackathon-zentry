"""M3 acceptance checks: case grouping, investigator grounding (every cited id exists and came from a
tool), agent write isolation (read tools are READ ONLY; only propose_action writes), analyst decisions
with audit + labels + role checks, and the Case Detail page. Run after `make reset && make replay`."""

import json
import os
import sys
import time

import httpx
import psycopg

from zt_worker.agent.investigator import persist
from zt_worker.agent.tools import SCHEMAS, TOOLS, WRITE_TOOLS, Tools, ToolError
from zt_worker.agent.validator import validate

API = "http://127.0.0.1:8000"
WEB = "http://localhost:3000"
SUPABASE = os.environ["SUPABASE_URL"]
results: list[tuple[bool, str, str]] = []


def check(ok, name, detail=""):
    results.append((bool(ok), name, str(detail)))


def token(role: str) -> str:
    r = httpx.post(f"{SUPABASE}/auth/v1/token", params={"grant_type": "password"},
                   headers={"apikey": os.environ["PUBLIC_SUPABASE_ANON_KEY"]},
                   json={"email": f"{role}@demo.zentry.local", "password": os.environ["DEMO_PASSWORD"]})
    return r.json()["access_token"]


def grouping(conn):
    rows = conn.execute("""
        select x.gt_ring, max(n) * 1.0 / sum(n) from (
          select a.gt_ring, l.case_id, count(*) n from public.case_links l
          join public.accounts a on a.id = l.account_id where a.gt_role = 'mule' group by 1, 2) x
        group by 1 order by 1""").fetchall()
    worst = min((r[1] for r in rows), default=0)
    check(len(rows) == 5 and worst >= 0.8, "each ring's mules land in one case (≥80%)",
          ", ".join(f"ring {r[0]}: {float(r[1]):.0%}" for r in rows))


def grounding(conn):
    cases = conn.execute("select id, agent_report from public.cases where agent_report is not null").fetchall()
    check(cases, "cases have been investigated", f"{len(cases)} cases")
    bad = []
    for cid, report in cases:
        ids = report["validation"]["cited"]
        if not report["validation"]["ok"]:
            bad.append(str(cid))
            continue
        txns = [i for i in ids if i.startswith("TX")]
        accts = [i for i in ids if i.startswith("A")]
        n = conn.execute("select (select count(*) from public.transactions where id = any(%s))"
                         " + (select count(*) from public.accounts where id = any(%s))", (txns, accts)).fetchone()[0]
        if n != len(ids):
            bad.append(str(cid))
    check(not bad, "independent re-check: every cited id exists in the DB", f"failing={bad}" if bad else
          f"{sum(len(r['validation']['cited']) for _, r in cases)} ids across {len(cases)} reports")
    shown = conn.execute("""select count(*) from public.cases where ai_summary is not null
                            and not (agent_report->'validation'->>'ok')::bool""").fetchone()[0]
    check(shown == 0, "no unvalidated summary is shown to analysts")

    # negative test: a report citing a fake id must be rejected and hidden
    cid = conn.execute("insert into public.cases (type, title) values ('mule', 'validator test') returning id").fetchone()[0]
    conn.commit()
    tools = Tools(conn, str(cid))
    fake = {"summary": "Money went from A0000001 to A9999999 via TX99999999.", "str_draft": "x"}
    v = validate(conn, fake, tools.seen_ids)
    check(not v.ok and "TX99999999" in v.missing_in_db and "A0000001" in v.not_from_tools,
          "validator rejects invented and ungrounded ids", v.as_dict())
    persist(conn, str(cid), fake, v.as_dict(), [{"action": "close", "rationale": "x", "evidence": []}],
            [], "test", "test", 0)
    row = conn.execute("""select ai_summary, (select count(*) from public.case_proposals where case_id = %s)
                          from public.cases where id = %s""", (cid, cid)).fetchone()
    check(row == (None, 0), "rejected report: summary hidden, proposals dropped", row)
    try:
        tools.propose_action("recommend_freeze", "x", ["A0000001"])
        check(False, "propose_action refuses evidence no tool returned")
    except ToolError as e:
        check(True, "propose_action refuses evidence no tool returned", e)
    conn.execute("delete from public.cases where id = %s", (cid,))
    conn.commit()


def isolation(conn):
    names = {s["function"]["name"] for s in SCHEMAS}
    check(names == set(TOOLS) and WRITE_TOOLS == {"propose_action"}, "agent toolset: only propose_action writes",
          sorted(names))
    cid = conn.execute("select id from public.cases limit 1").fetchone()[0]
    tools = Tools(conn, str(cid))
    try:
        tools._read("update public.accounts set status = 'frozen' where id = 'A0000001' returning id")
        check(False, "read tools run in READ ONLY transactions", "update succeeded!")
    except psycopg.errors.ReadOnlySqlTransaction:
        check(True, "read tools run in READ ONLY transactions", "UPDATE rejected by Postgres")
    conn.rollback()
    before = conn.execute("select count(*) from public.audit_log").fetchone()[0]
    tools.call("get_case", {})
    after = conn.execute("select count(*) from public.audit_log").fetchone()[0]
    check(before == after, "tool calls themselves write nothing")


def decisions(conn):
    case_id, = conn.execute("""select id from public.cases where risk_level = 'critical'
                              order by title limit 1""").fetchone()
    analyst, collections = token("analyst"), token("collections")
    r = httpx.post(f"{API}/cases/{case_id}/decision", json={"decision": "freeze"},
                   headers={"Authorization": f"Bearer {collections}"})
    check(r.status_code == 403, "collections role cannot decide mule cases", f"HTTP {r.status_code}")
    r = httpx.post(f"{API}/cases/{case_id}/decision", json={"decision": "freeze"})
    check(r.status_code == 401, "anonymous request rejected", f"HTTP {r.status_code}")

    audit_before = conn.execute("select count(*) from public.audit_log where actor like 'user:%%'").fetchone()[0]
    r = httpx.post(f"{API}/cases/{case_id}/decision", headers={"Authorization": f"Bearer {analyst}"},
                   json={"decision": "freeze", "approve_str": True, "str_text": "Approved STR text", "note": "m3 check"})
    body = r.json()
    check(r.status_code == 200 and body["frozen_accounts"], "analyst freezes the case's accounts",
          f"{len(body.get('frozen_accounts', []))} frozen")
    frozen = conn.execute("""select count(*) from public.accounts where status = 'frozen'
                             and id = any(%s)""", (body.get("frozen_accounts", []),)).fetchone()[0]
    check(frozen == len(body.get("frozen_accounts", [])), "accounts.status = frozen in the ledger")
    c = conn.execute("select status, disposition, str_approved_at is not null, str_draft from public.cases where id = %s",
                     (case_id,)).fetchone()
    check(c[:3] == ("escalated", "fraud", True) and c[3] == "Approved STR text",
          "case escalated, labelled fraud, STR approved", c[:3])
    a = conn.execute("""select before_json, after_json from public.audit_log where object_ref = %s
                        and action = 'decision:freeze' order by id desc limit 1""", (f"case:{case_id}",)).fetchone()
    audit_after = conn.execute("select count(*) from public.audit_log where actor like 'user:%%'").fetchone()[0]
    check(a and a[0] and a[1]["frozen_accounts"] and audit_after == audit_before + 1,
          "audit_log has before/after for the decision")
    p = conn.execute("""select count(*) filter (where status = 'pending'),
                               count(*) filter (where status = 'accepted' and action = 'recommend_freeze')
                        from public.case_proposals where case_id = %s""", (case_id,)).fetchone()
    check(p[0] == 0, "agent proposals resolved by the decision", f"pending={p[0]} accepted_freeze={p[1]}")
    labels = conn.execute("select count(*) from public.cases where disposition in ('fraud', 'false_positive')").fetchone()[0]
    check(labels >= 1, "decision becomes a training label (cases.disposition)", f"{labels} labelled cases")

    # re-run investigation through the API and wait for it
    other, ts = conn.execute("""select id, investigated_at from public.cases where status <> 'closed'
                                and id <> %s and agent_report is not null limit 1""", (case_id,)).fetchone()
    r = httpx.post(f"{API}/cases/{other}/investigate", headers={"Authorization": f"Bearer {analyst}"})
    ok = False
    for _ in range(40):
        time.sleep(0.5)
        conn.rollback()
        if conn.execute("select investigated_at > %s from public.cases where id = %s", (ts, other)).fetchone()[0]:
            ok = True
            break
    check(r.status_code == 202 and ok, "API → NATS job → investigator updates the case", f"HTTP {r.status_code}")
    return case_id


def page(case_id):
    with httpx.Client(base_url=WEB, headers={"Origin": WEB}) as http:
        http.post("/login", data={"email": "analyst@demo.zentry.local", "password": os.environ["DEMO_PASSWORD"]})
        r = http.get(f"/cases/{case_id}")
        check(r.status_code == 200 and "ids verified" in r.text and "frozen" in r.text and "Agent proposals" in r.text,
              "Case Detail shows verified summary, frozen accounts, proposals", f"HTTP {r.status_code}")
        r = http.get("/cases")
        check(r.status_code == 200 and "open cases" in r.text, "Cases list renders")


def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        grouping(conn)
        grounding(conn)
        isolation(conn)
        case_id = decisions(conn)
    page(case_id)
    width = max(len(n) for _, n, _ in results)
    for ok, name, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail[:110]}")
    failed = sum(not ok for ok, _, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
