"""M1 acceptance checks: schema + RLS, seeded counts vs. the generator manifest, demo logins per role,
row-level security behaviour, and local service health. Exits non-zero on any failure."""

import json
import os
import sys
from collections import Counter
from pathlib import Path

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "data/generated/manifest.json").read_text())
SUPABASE_URL = os.environ["SUPABASE_URL"]
ANON = os.environ["PUBLIC_SUPABASE_ANON_KEY"]
TABLES = ["customers", "accounts", "transactions", "settlements", "scenarios", "alerts", "cases", "case_links",
          "recon_runs", "recon_matches", "follow_ups", "messages", "model_versions", "audit_log", "outbox",
          "train_runs"]
ROLES = ["analyst", "finance_ops", "collections", "compliance_manager"]

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((bool(ok), name, detail))


def db_checks(cur) -> None:
    cur.execute("""select c.relname, c.relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace
                   where n.nspname = 'public' and c.relkind = 'r'""")
    rls = dict(cur.fetchall())
    missing = [t for t in TABLES if t not in rls]
    check(not missing, "all 16 tables exist", f"missing={missing}" if missing else "")
    no_rls = [t for t in TABLES if not rls.get(t)]
    check(not no_rls, "RLS enabled on every table", f"without RLS={no_rls}" if no_rls else "")
    cur.execute("select 1 from pg_extension where extname = 'vector'")
    check(cur.fetchone(), "pgvector installed")
    cur.execute("""select data_type from information_schema.columns
                   where table_schema='public' and column_name like '%%_satang'""")
    types = {r[0] for r in cur.fetchall()}
    check(types == {"bigint"}, "all *_satang columns are BIGINT", str(types))

    c = MANIFEST["counts"]
    for table in ["customers", "accounts", "transactions", "settlements"]:
        cur.execute(f"select count(*) from public.{table}")
        n = cur.fetchone()[0]
        check(n == c[table], f"{table} count matches manifest", f"{n:,} vs {c[table]:,}")
    check(c["customers"] == 10_000, "10,000 customers")
    check(190_000 <= c["transactions"] <= 210_000, "~200,000 transactions", f"{c['transactions']:,}")
    cur.execute("select max(ts) - min(ts) from public.transactions")
    span = cur.fetchone()[0]
    check(29 <= span.days <= 30, "transactions span 30 days", str(span))

    cur.execute("""select gt_ring, count(*), count(distinct gt_layer) from public.accounts
                   where gt_role = 'mule' group by gt_ring order by gt_ring""")
    rings = cur.fetchall()
    check(len(rings) == 5, "5 mule rings", str(len(rings)))
    for ring, size, layers in rings:
        check(10 <= size <= 20 and layers == 3, f"ring {ring}: 10–20 accounts in 3 layers", f"{size} accts, {layers} layers")
        # money must actually flow victim → L1 → L2 → L3 inside the ring
        cur.execute("""select coalesce(f.gt_layer, 0), coalesce(t.gt_layer, 0), count(*)
                       from public.transactions x
                       join public.accounts f on f.id = x.from_account
                       join public.accounts t on t.id = x.to_account
                       where x.gt_ring = %s group by 1, 2""", (ring,))
        hops = {(a, b) for a, b, _ in cur.fetchall()}
        check({(0, 1), (1, 2), (2, 3), (3, 0)} <= hops, f"ring {ring}: victim→L1→L2→L3→cash-out flow",
              str(sorted(hops)))

    cur.execute("select count(*) from public.transactions where gt_is_fraud")
    check(cur.fetchone()[0] == c["fraud_transactions"], "fraud labels match manifest")

    expected = Counter(b["type"] for b in MANIFEST["breaks"])
    cur.execute("select gt_break_type, count(*) from public.settlements where gt_break_type is not null group by 1")
    found = dict(cur.fetchall())
    for kind, n in expected.items():
        if kind == "missing_in_bank":  # no settlement row by definition: the ledger txn must exist, unsettled
            refs = [b["ref_no"] for b in MANIFEST["breaks"] if b["type"] == kind]
            cur.execute("""select count(*) from public.transactions t where t.ref_no = any(%s)
                           and not exists (select 1 from public.settlements s where s.ref_no = t.ref_no)""", (refs,))
            got = cur.fetchone()[0]
        else:
            got = found.get(kind, 0)
        check(got == n, f"break '{kind}' embedded", f"{got}/{n}")


def login(http: httpx.Client, role: str) -> str | None:
    r = http.post("/auth/v1/token", params={"grant_type": "password"},
                  json={"email": f"{role}@demo.zentry.local", "password": os.environ["DEMO_PASSWORD"]})
    if r.status_code != 200:
        check(False, f"login as {role}", f"HTTP {r.status_code}")
        return None
    body = r.json()
    got = body["user"]["app_metadata"].get("role")
    check(got == role, f"login as {role}", f"role claim={got}")
    return body["access_token"]


def count(http: httpx.Client, token: str, table: str, select: str = "id") -> int | str:
    r = http.get(f"/rest/v1/{table}", params={"select": select, "limit": 1},
                 headers={"Authorization": f"Bearer {token}", "Prefer": "count=exact"})
    if r.status_code >= 400:
        return f"HTTP {r.status_code}"
    return int(r.headers["content-range"].split("/")[1])


def auth_checks() -> None:
    with httpx.Client(base_url=SUPABASE_URL, headers={"apikey": ANON}, timeout=15) as http:
        tokens = {role: login(http, role) for role in ROLES}
        a, f, col = tokens["analyst"], tokens["finance_ops"], tokens["collections"]
        if a:
            check(isinstance(n := count(http, a, "transactions"), int) and n > 0, "RLS: analyst reads transactions", str(n))
            check(count(http, a, "settlements") == 0, "RLS: analyst cannot read settlements")
            check(isinstance(count(http, a, "accounts", "id,gt_role"), str), "RLS: ground-truth columns hidden")
        if f:
            check(isinstance(n := count(http, f, "settlements"), int) and n > 0, "RLS: finance_ops reads settlements", str(n))
        if col:
            check(count(http, col, "audit_log") == 0, "RLS: collections cannot read audit_log")
        r = http.get("/rest/v1/transactions", params={"select": "id", "limit": 1})
        check(r.status_code >= 400 or r.json() == [], "RLS: anonymous sees no transactions")


def service_checks() -> None:
    for name, url in [("api /healthz (db + nats)", "http://127.0.0.1:8000/healthz"),
                      ("nats JetStream", "http://127.0.0.1:8222/healthz?js-enabled-only=true"),
                      ("web /login", "http://127.0.0.1:3000/login")]:
        try:
            r = httpx.get(url, timeout=5)
            check(r.status_code == 200, name, f"HTTP {r.status_code} {r.text[:80] if r.status_code != 200 else ''}")
        except httpx.HTTPError as e:
            check(False, name, e.__class__.__name__)


def main() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        db_checks(cur)
    auth_checks()
    service_checks()
    width = max(len(n) for _, n, _ in results)
    for ok, name, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = sum(not ok for ok, _, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
