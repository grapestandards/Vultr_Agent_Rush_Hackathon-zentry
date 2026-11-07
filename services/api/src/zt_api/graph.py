"""Graph Explorer data: the money-flow network around a case or account, hop expansion,
network groups (flagged accounts connected by money flow) and Trace from victim.

Trace uses the proportional (haircut) rule: every transfer out of an account carries the victim's
share of that account's running balance, so money pooled from several victims is split fairly.
Balances start at zero at the victim's first payment (earlier funds are unknown); a transfer larger
than the running balance is treated as including the account's own funds. All amounts are integer satang."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

import networkx as nx
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row

from zt_core.settings import env

from .auth import User, current_user, require

router = APIRouter(prefix="/graph", tags=["graph"])

PER_NODE = 12           # top counterparties shown per expanded account
MAX_TXNS = 1500
TRACE_HORIZON = timedelta(hours=72)
TRACE_ROUNDS = 6


def _connect():
    return psycopg.connect(env("DATABASE_URL"), row_factory=dict_row)


def _window(conn, case: str | None, accounts: list[str]) -> tuple[datetime, datetime]:
    """Business-time window: the case's alert span (±24h), else around the account's last alert."""
    if case:
        row = conn.execute("""select min(a.txn_ts) lo, max(a.txn_ts) hi from public.case_links l
                              join public.alerts a on a.id = l.alert_id where l.case_id = %s""", (case,)).fetchone()
    else:
        row = conn.execute("select min(txn_ts) lo, max(txn_ts) hi from public.alerts where account_id = any(%s)",
                           (accounts,)).fetchone()
    if row and row["hi"]:
        return row["lo"] - timedelta(hours=24), row["hi"] + timedelta(hours=24)
    hi = conn.execute("select max(ts) hi from public.transactions where from_account = any(%s) or to_account = any(%s)",
                      (accounts, accounts)).fetchone()["hi"]
    if not hi:
        raise HTTPException(404, "no transactions for these accounts")
    return hi - timedelta(hours=72), hi + timedelta(minutes=1)


def _txns_around(conn, seeds: list[str], start: datetime, end: datetime) -> dict[str, dict]:
    """Transfers between seeds, plus each seed's top counterparties and anyone linked to 2+ seeds."""
    rows = conn.execute("""
        select id, from_account, to_account, amount_satang, ts from public.transactions
        where ts between %s and %s and (from_account = any(%s) or to_account = any(%s))""",
                        (start, end, seeds, seeds)).fetchall()
    seed_set = set(seeds)
    volume: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        for me, cp in ((r["from_account"], r["to_account"]), (r["to_account"], r["from_account"])):
            if me in seed_set and cp not in seed_set:
                volume[me][cp] += r["amount_satang"]
    linked: dict[str, int] = defaultdict(int)
    for cps in volume.values():
        for cp in cps:
            linked[cp] += 1
    keep = set(seed_set) | {cp for cp, n in linked.items() if n >= 2}
    for cps in volume.values():
        keep.update(sorted(cps, key=cps.get, reverse=True)[:PER_NODE])
    chosen = [r for r in rows if r["from_account"] in keep and r["to_account"] in keep]
    chosen.sort(key=lambda r: r["amount_satang"], reverse=True)
    return {r["id"]: r for r in chosen[:MAX_TXNS]}


def _nodes(conn, ids: set[str], txns: list[dict]) -> list[dict]:
    flow_in: dict[str, int] = defaultdict(int)
    flow_out: dict[str, int] = defaultdict(int)
    for t in txns:
        flow_out[t["from_account"]] += t["amount_satang"]
        flow_in[t["to_account"]] += t["amount_satang"]
    rows = conn.execute("""
        select a.id, a.type, a.status, c.display_en as name, c.display_th as name_th, c.kyc_level,
               (select max(score) from public.alerts al where al.account_id = a.id) as risk,
               (select array_agg(distinct l.case_id::text) from public.case_links l
                 where l.account_id = a.id) as cases
        from public.accounts a join public.customers c on c.id = a.customer_id
        where a.id = any(%s)""", (list(ids),)).fetchall()
    return [{**r, "cases": r["cases"] or [], "in_satang": flow_in[r["id"]], "out_satang": flow_out[r["id"]]}
            for r in rows]


def _groups(nodes: list[dict], txns: list[dict]) -> list[dict]:
    """Networks: flagged accounts connected by money flow, plus unflagged pass-through accounts
    (money in from and out to the network). Victims only pay in and merchants only receive, so
    they stay outside the box."""
    by_id = {n["id"]: n for n in nodes}
    flagged = {n["id"] for n in nodes if n["risk"]}
    sends_to, gets_from = defaultdict(set), defaultdict(set)
    for t in txns:
        sends_to[t["from_account"]].add(t["to_account"])
        gets_from[t["to_account"]].add(t["from_account"])
    passthrough = {a for a in by_id if a not in flagged and by_id[a]["type"] != "merchant"
                   and sends_to[a] & flagged and gets_from[a] & flagged}
    members_all = flagged | passthrough
    g = nx.Graph()
    g.add_nodes_from(members_all)
    g.add_edges_from((t["from_account"], t["to_account"]) for t in txns
                     if t["from_account"] in members_all and t["to_account"] in members_all)
    groups = []
    for members in sorted(nx.connected_components(g), key=len, reverse=True):
        n_flagged = len(members & flagged)
        if n_flagged < 2:
            continue
        cases: dict[str, int] = defaultdict(int)
        for m in members:
            for c in by_id[m]["cases"]:
                cases[c] += 1
        groups.append({"id": f"g{len(groups) + 1}", "members": sorted(members), "flagged": n_flagged,
                       "case_id": max(cases, key=cases.get) if cases else None})
    return groups


def _payload(conn, txns: dict[str, dict], start: datetime, end: datetime, seeds: list[str]) -> dict:
    tx = sorted(txns.values(), key=lambda r: r["ts"])
    ids = set(seeds) | {r["from_account"] for r in tx} | {r["to_account"] for r in tx}
    nodes = _nodes(conn, ids, tx)
    return {"window": {"start": start, "end": end}, "seeds": seeds, "nodes": nodes,
            "transactions": tx, "groups": _groups(nodes, tx)}


@router.get("/network")
def network(case: str | None = None, accounts: list[str] = Query(default=[]),
            start: datetime | None = None, end: datetime | None = None,
            user: User = Depends(current_user)) -> dict:
    """The case's accounts (or the given accounts) and one hop of counterparties."""
    require(user, "analyst", "compliance_manager")
    with _connect() as conn:
        seeds = list(accounts)
        if case:
            seeds += [r["account_id"] for r in conn.execute(
                "select distinct account_id from public.case_links where case_id = %s and account_id is not null",
                (case,))]
        seeds = sorted(set(seeds))
        if not seeds:
            raise HTTPException(404, "no accounts to show")
        if not (start and end):
            start, end = _window(conn, case, seeds)
        return _payload(conn, _txns_around(conn, seeds, start, end), start, end, seeds)


def _victim_candidates(conn, seeds: list[str], start: datetime, end: datetime) -> list[dict]:
    """Senders into the network who are not alerted themselves: the likely scam victims."""
    return conn.execute("""
        select t.from_account as account_id, c.display_en as name, sum(t.amount_satang)::bigint as paid_satang,
               count(*) as payments, min(t.ts) as first_ts
        from public.transactions t
        join public.accounts a on a.id = t.from_account join public.customers c on c.id = a.customer_id
        where t.to_account = any(%s) and t.ts between %s and %s and not t.from_account = any(%s)
          and a.type <> 'merchant'
          and not exists (select 1 from public.alerts al where al.account_id = t.from_account)
        group by 1, 2 order by paid_satang desc limit 8""", (seeds, start, end, seeds)).fetchall()


def trace_money(conn, victim: str, into: list[str], start: datetime, end: datetime) -> dict:
    """Follow the victim's payments into `into` forward in time (proportional rule)."""
    entry = conn.execute("""select id, from_account, to_account, amount_satang, ts from public.transactions
                            where from_account = %s and to_account = any(%s) and ts between %s and %s
                            order by ts, id""", (victim, into, start, end)).fetchall()
    if not entry:
        raise HTTPException(404, "this account made no payments into the network")
    t0 = entry[0]["ts"]
    merchants = {r["id"] for r in conn.execute("select id from public.accounts where type = 'merchant'")}
    reached = {t["to_account"] for t in entry}
    fetched: set[str] = set()
    txns: dict[str, dict] = {t["id"]: t for t in entry}
    for _ in range(TRACE_ROUNDS):
        todo = sorted(reached - fetched - merchants)  # merchants are where money leaves the wallet
        if not todo:
            break
        for r in conn.execute("""select id, from_account, to_account, amount_satang, ts from public.transactions
                                 where (from_account = any(%s) or to_account = any(%s)) and ts between %s and %s""",
                              (todo, todo, t0, t0 + TRACE_HORIZON)):
            txns[r["id"]] = r
        fetched |= set(todo)
        _, moved = _simulate({t["id"] for t in entry}, txns.values())
        reached |= {t["to_account"] for t in moved}
    held, moved = _simulate({t["id"] for t in entry}, txns.values())
    paid = sum(t["amount_satang"] for t in entry)
    cashed = sum(v for a, v in held.items() if a in merchants)
    still = {a: v for a, v in held.items() if a not in merchants and v > 0}
    return {
        "victim": victim, "paid_satang": paid, "first_ts": t0,
        "held_satang": sum(still.values()), "cashed_out_satang": cashed,
        "elsewhere_satang": paid - sum(still.values()) - cashed,  # rounding / left via non-traced paths
        "held": sorted(({"account_id": a, "satang": v} for a, v in still.items()), key=lambda h: -h["satang"]),
        "cash_out": sorted(({"account_id": a, "satang": v} for a, v in held.items() if a in merchants and v),
                           key=lambda h: -h["satang"]),
        "path": moved,
    }


def _simulate(entry_ids: set[str], txns) -> tuple[dict[str, int], list[dict]]:
    """Replay transfers in time order; returns traced satang held per account and the traced hops."""
    tainted: dict[str, int] = defaultdict(int)
    balance: dict[str, int] = defaultdict(int)
    moved_rows = []
    for t in sorted(txns, key=lambda r: (r["ts"], r["id"])):
        src, dst, amount = t["from_account"], t["to_account"], t["amount_satang"]
        if t["id"] in entry_ids:
            moved = amount
        else:
            base = max(balance[src], amount)
            moved = min(tainted[src], amount, tainted[src] * amount // base) if tainted[src] else 0
            tainted[src] -= moved
        balance[src] -= amount
        balance[dst] += amount
        if moved > 0:
            tainted[dst] += moved
            moved_rows.append({**t, "traced_satang": moved})
    return dict(tainted), moved_rows


@router.get("/trace")
def trace(case: str | None = None, account: str | None = None, victim: str | None = None,
          user: User = Depends(current_user)) -> dict:
    """Trace from victim: where the victim's money went and how much is still held, per account."""
    require(user, "analyst", "compliance_manager")
    with _connect() as conn:
        if case:
            seeds = sorted({r["account_id"] for r in conn.execute(
                "select account_id from public.case_links where case_id = %s and account_id is not null", (case,))})
        elif account:
            seeds = [account]
        else:
            raise HTTPException(400, "pass case or account")
        start, end = _window(conn, case, seeds)
        start -= timedelta(days=3)  # victims pay in before the first alert fires
        candidates = _victim_candidates(conn, seeds, start, end)
        victim = victim or (candidates[0]["account_id"] if candidates else None)
        if not victim:
            raise HTTPException(404, "no likely victim found")
        result = trace_money(conn, victim, seeds, start, end)
        ids = {victim} | {t["to_account"] for t in result["path"]} | {t["from_account"] for t in result["path"]}
        result["nodes"] = _nodes(conn, ids, result["path"])
        result["candidates"] = candidates
        return result
