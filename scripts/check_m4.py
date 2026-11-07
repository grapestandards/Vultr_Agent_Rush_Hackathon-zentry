"""M4 acceptance checks: from a case, the Graph Explorer shows the whole mule ring within 2 clicks
(Case Detail → "Open graph"), as one network; hop expansion, Trace from victim (money conserved, held
amounts land on ring accounts), time window, roles and the page itself. Ground truth (gt_*) is used
here for evaluation only. Run after `make reset && make replay`."""

import os
import re
import sys
import time

import httpx
import psycopg

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


def ring_cases(conn) -> dict[int, tuple[str, set[str]]]:
    """Each ring's active mules (in a ring transaction) and the case holding most of them."""
    out = {}
    for ring, mules in conn.execute("""
            select a.gt_ring, array_agg(distinct a.id) from public.accounts a
            join public.transactions t on a.id in (t.from_account, t.to_account) and t.gt_ring = a.gt_ring
            where a.gt_role = 'mule' group by 1 order by 1"""):
        case = conn.execute("""select case_id from public.case_links where account_id = any(%s)
                               group by 1 order by count(*) desc limit 1""", (mules,)).fetchone()
        out[ring] = (str(case[0]) if case else None, set(mules))
    return out


def main():
    analyst = {"Authorization": f"Bearer {token('analyst')}"}
    http = httpx.Client(base_url=API, headers=analyst, timeout=30)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rings = ring_cases(conn)
        check(len(rings) == 5 and all(c for c, _ in rings.values()), "every ring has a case", len(rings))

        full, one_net, slow, networks = [], [], [], {}
        for ring, (case, mules) in rings.items():
            t0 = time.time()
            net = http.get("/graph/network", params={"case": case}).json()
            slow.append(time.time() - t0)
            networks[ring] = (case, net)
            shown = {n["id"] for n in net["nodes"]}
            full.append((ring, len(mules & shown), len(mules)))
            best = max(net["groups"], key=lambda g: len(set(g["members"]) & mules), default=None)
            one_net.append(best is not None and mules <= set(best["members"]) and best["case_id"] == case)
        check(all(a == b for _, a, b in full), "whole ring visible on the case graph (click 1 of 2)",
              ", ".join(f"ring {r}: {a}/{b}" for r, a, b in full))
        check(all(one_net), "each ring is boxed as one network that opens its case", one_net)
        check(max(slow) < 2, "graph loads fast", f"max {max(slow):.2f}s")

        case, net = networks[1]
        merchants = {r[0] for r in conn.execute("select id from public.accounts where type = 'merchant'")}
        boxed = {m for g in net["groups"] for m in g["members"]}
        check(not boxed & merchants, "cash-out merchants stay outside the network box")
        lo, hi = net["window"]["start"], net["window"]["end"]
        check(all(lo <= t["ts"] <= hi for t in net["transactions"]), "all transfers inside the time window",
              f"{lo[:16]} → {hi[:16]}")
        ids = [t["id"] for t in net["transactions"]]
        n = conn.execute("select count(*) from public.transactions where id = any(%s)", (ids,)).fetchone()[0]
        check(n == len(ids) and all(isinstance(t["amount_satang"], int) for t in net["transactions"]),
              "every edge is a real transaction with integer satang", f"{len(ids)} transfers")

        # hop expansion from a node at the edge of the case graph
        edge_node = next(nd["id"] for nd in net["nodes"] if nd["id"] not in net["seeds"] and nd["type"] != "merchant")
        exp = http.get("/graph/network", params={"accounts": edge_node, "start": lo, "end": hi}).json()
        new = {nd["id"] for nd in exp["nodes"]} - {nd["id"] for nd in net["nodes"]}
        check(exp["seeds"] == [edge_node] and new, "expand 1 hop adds the account's counterparties", f"+{len(new)} accounts")

        # Trace from victim
        traces = []
        for ring, (case, mules) in rings.items():
            tr = http.get("/graph/trace", params={"case": case}).json()
            role = conn.execute("select gt_role from public.accounts where id = %s", (tr["victim"],)).fetchone()[0]
            cand_roles = [r[0] for r in conn.execute("select gt_role from public.accounts where id = any(%s)",
                                                     ([c["account_id"] for c in tr["candidates"]],))]
            conserved = tr["held_satang"] + tr["cashed_out_satang"] + tr["elsewhere_satang"] == tr["paid_satang"]
            held_on_ring = {h["account_id"] for h in tr["held"]} <= mules
            cash_ok = {c["account_id"] for c in tr["cash_out"]} <= merchants
            capped = all(0 < p["traced_satang"] <= p["amount_satang"] for p in tr["path"])
            traces.append((ring, role, cand_roles.count("victim"), len(cand_roles), conserved, held_on_ring,
                           cash_ok, capped, tr))
        check(all(t[1] == "victim" for t in traces), "auto-picked victim is a real victim (gt check)",
              ", ".join(f"ring {t[0]}: {t[2]}/{t[3]} candidates are victims" for t in traces))
        check(all(t[4] for t in traces), "trace conserves money: held + cashed out + elsewhere = paid")
        check(all(t[5] and t[6] for t in traces), "held money sits on ring mules; cash-out only at merchants")
        check(all(t[7] for t in traces), "traced amount never exceeds the transfer amount")
        tr = traces[0][8]
        ids = [p["id"] for p in tr["path"]]
        n = conn.execute("select count(*) from public.transactions where id = any(%s)", (ids,)).fetchone()[0]
        check(n == len(ids) and tr["held_satang"] > 0, "trace path cites real transaction ids",
              f"victim paid {tr['paid_satang'] / 100:,.0f} THB → held {tr['held_satang'] / 100:,.0f} THB "
              f"in {len(tr['held'])} accounts, cashed out {tr['cashed_out_satang'] / 100:,.0f} THB")
        other = tr["candidates"][1]["account_id"]
        tr2 = http.get("/graph/trace", params={"case": rings[1][0], "victim": other}).json()
        check(tr2["victim"] == other and tr2["path"], "trace another victim on demand", other)

    # roles
    coll = {"Authorization": f"Bearer {token('collections')}"}
    r = httpx.get(f"{API}/graph/network", params={"case": rings[1][0]}, headers=coll)
    check(r.status_code == 403, "collections role cannot open the graph", f"HTTP {r.status_code}")
    r = httpx.get(f"{API}/graph/network", params={"case": rings[1][0]})
    check(r.status_code == 401, "anonymous request rejected", f"HTTP {r.status_code}")

    # pages: case → graph link (click 1), graph page with trace
    with httpx.Client(base_url=WEB, headers={"Origin": WEB}) as web:
        web.post("/login", data={"email": "analyst@demo.zentry.local", "password": os.environ["DEMO_PASSWORD"]})
        case = rings[1][0]
        page = web.get(f"/cases/{case}").text
        link = re.search(r'href="(/graph\?case=' + case + ')"', page)
        check(link, "Case Detail links to its network graph", link.group(1)[:60] if link else "no link")
        r = web.get(f"/graph?case={case}&trace=1")
        check(r.status_code == 200 and 'data-testid="graph"' in r.text and "Trace from victim" in r.text,
              "Graph Explorer page renders with Trace", f"HTTP {r.status_code}")
        r = web.get("/graph/data", params={"kind": "network", "accounts": edge_node, "start": lo, "end": hi})
        check(r.status_code == 200 and r.json()["nodes"], "browser expand proxy works", f"HTTP {r.status_code}")

    width = max(len(n) for _, n, _ in results)
    for ok, name, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail[:110]}")
    failed = sum(not ok for ok, _, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
