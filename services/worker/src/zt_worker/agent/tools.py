"""Investigator tools. Every read tool runs in a READ ONLY database transaction, so even a buggy or
prompt-injected tool call cannot change data. `propose_action` is the single writer and only
inserts a pending proposal for a human to accept or reject."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

from zt_core.money import format_thb

TYPOLOGY_DIR = Path(__file__).resolve().parents[5] / "data" / "typologies"
TXN_RE = re.compile(r"\bTX[A-Z0-9]{8,}\b")
ACCT_RE = re.compile(r"\bA\d{7}\b")


class ToolError(Exception):
    pass


class Tools:
    def __init__(self, conn: psycopg.Connection, case_id: str) -> None:
        self.conn = conn
        self.case_id = case_id
        self.seen_ids: set[str] = set()   # every id any tool returned — the agent may only cite these
        self.proposals: list[dict] = []
        self._anchor: datetime | None = None

    def anchor(self) -> datetime:
        """Time windows are measured back from the case's latest alert, not from 'now': cases are often
        reviewed days after the activity."""
        if self._anchor is None:
            self._anchor = self._read("""
                select coalesce((select max(a.txn_ts) from public.case_links l join public.alerts a on a.id = l.alert_id
                                 where l.case_id = %s), (select max(ts) from public.transactions)) as ts""",
                                      (self.case_id,))[0]["ts"]
        return self._anchor

    # ---------------------------------------------------------------- plumbing
    def _read(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        with self.conn.transaction():
            self.conn.execute("set transaction read only")
            cur = self.conn.execute(sql, params)
            cols = [c.name for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return rows

    def _remember(self, obj: Any) -> Any:
        text = json.dumps(obj, default=str)
        self.seen_ids.update(TXN_RE.findall(text))
        self.seen_ids.update(ACCT_RE.findall(text))
        return obj

    def call(self, name: str, args: dict) -> dict:
        fn: Callable[..., dict] | None = TOOLS.get(name)
        if fn is None:
            raise ToolError(f"unknown tool {name}")
        return self._remember(fn(self, **args))

    # ---------------------------------------------------------------- read tools
    def get_case(self) -> dict:
        case = self._read("select id, type, status, title, created_at from public.cases where id = %s", (self.case_id,))
        if not case:
            raise ToolError("case not found")
        alerts = self._read("""
            select a.account_id, a.transaction_id, a.score, a.rule_hits, a.reason, a.txn_ts
            from public.case_links l join public.alerts a on a.id = l.alert_id
            where l.case_id = %s order by a.txn_ts""", (self.case_id,))
        return {"case": case[0], "alerts": alerts}

    def get_account_history(self, account_id: str, days: int = 7, limit: int = 40) -> dict:
        acct = self._read("""
            select a.id, a.type, a.status, a.opened_at, c.name_en, c.name_th, c.kyc_level
            from public.accounts a join public.customers c on c.id = a.customer_id where a.id = %s""", (account_id,))
        if not acct:
            raise ToolError(f"account {account_id} not found")
        end = self.anchor() + timedelta(hours=24)
        since = end - timedelta(days=days)
        txns = self._read("""
            select id, ts, case when from_account = %(a)s then 'out' else 'in' end as direction,
                   case when from_account = %(a)s then to_account else from_account end as counterparty,
                   amount_satang, channel, device_id
            from public.transactions
            where (from_account = %(a)s or to_account = %(a)s) and ts between %(since)s and %(end)s
            order by ts desc limit %(limit)s""", {"a": account_id, "since": since, "end": end, "limit": limit})
        total_in = sum(t["amount_satang"] for t in txns if t["direction"] == "in")
        total_out = sum(t["amount_satang"] for t in txns if t["direction"] == "out")
        for t in txns:
            t["amount"] = format_thb(t.pop("amount_satang"))
        return {"account": acct[0], "window_days": days, "total_in": format_thb(total_in),
                "total_out": format_thb(total_out), "transactions": txns}

    def expand_graph(self, account_id: str, hops: int = 2, hours: int = 72) -> dict:
        hops = max(1, min(hops, 3))
        end = self.anchor() + timedelta(hours=24)
        since = end - timedelta(hours=hours + 24)
        frontier, nodes, edges = {account_id}, {account_id}, {}
        for _ in range(hops):
            rows = self._read("""
                select id, from_account, to_account, amount_satang, ts from public.transactions
                where ts between %s and %s and (from_account = any(%s) or to_account = any(%s))
                order by amount_satang desc limit 300""", (since, end, list(frontier), list(frontier)))
            nxt = set()
            for r in rows:
                edges[r["id"]] = r
                nxt.update({r["from_account"], r["to_account"]})
            frontier = nxt - nodes
            nodes |= nxt
        flagged = {r["account_id"]: r["max"] for r in self._read(
            "select account_id, max(score) from public.alerts where account_id = any(%s) group by 1", (list(nodes),))}
        return {
            "center": account_id, "hops": hops, "window_hours": hours,
            "accounts": [{"id": n, "alert_score": flagged.get(n)} for n in sorted(nodes)][:80],
            "transfers": [{"id": e["id"], "from": e["from_account"], "to": e["to_account"],
                           "amount": format_thb(e["amount_satang"]), "amount_satang": e["amount_satang"],
                           "ts": e["ts"]}
                          for e in sorted(edges.values(), key=lambda e: e["ts"])][:120],
        }

    def screen_name(self, name: str) -> dict:
        hits = self._read("""
            select name_en, name_th, list, reason, round(extensions.similarity(name_en, %s)::numeric, 2) as similarity
            from public.watchlist where extensions.similarity(name_en, %s) > 0.4
            order by similarity desc limit 5""", (name, name))
        return {"query": name, "matches": hits}

    def search_typology(self, query: str) -> dict:
        """Local keyword search over data/typologies (Vultr Vector Store RAG replaces this when configured)."""
        words = {w for w in re.findall(r"[a-z]+", query.lower()) if len(w) > 2}
        scored = []
        for path in sorted(TYPOLOGY_DIR.glob("*.md")):
            text = path.read_text()
            score = sum(text.lower().count(w) for w in words)
            if score:
                scored.append((score, path.stem, text))
        scored.sort(reverse=True)
        return {"query": query, "documents": [{"id": s, "text": t[:1500]} for _, s, t in scored[:2]]}

    def similar_cases(self) -> dict:
        """Closed cases sharing rule hits with this one (pgvector embeddings replace this when configured)."""
        rows = self._read("""
            with mine as (select distinct unnest(a.rule_hits) r from public.case_links l
                          join public.alerts a on a.id = l.alert_id where l.case_id = %(c)s)
            select c.id, c.title, c.disposition, count(distinct r.r) as shared_rules
            from public.cases c join public.case_links l on l.case_id = c.id
            join public.alerts a on a.id = l.alert_id, unnest(a.rule_hits) r(r)
            where c.status = 'closed' and c.id <> %(c)s and r.r in (select r from mine)
            group by 1, 2, 3 order by shared_rules desc limit 3""", {"c": self.case_id})
        return {"similar_closed_cases": rows}

    # ---------------------------------------------------------------- the only writer
    def propose_action(self, action: str, rationale: str, evidence: list[str]) -> dict:
        if action not in {"close", "escalate", "recommend_freeze", "file_str"}:
            raise ToolError(f"invalid action {action}")
        unknown = [e for e in evidence if e not in self.seen_ids]
        if unknown:
            raise ToolError(f"evidence ids not returned by any tool: {unknown}")
        self.proposals.append({"action": action, "rationale": rationale, "evidence": evidence})
        return {"status": "recorded as pending proposal; a human must approve it"}


TOOLS: dict[str, Callable[..., dict]] = {
    "get_case": Tools.get_case,
    "get_account_history": Tools.get_account_history,
    "expand_graph": Tools.expand_graph,
    "screen_name": Tools.screen_name,
    "search_typology": Tools.search_typology,
    "similar_cases": Tools.similar_cases,
    "propose_action": Tools.propose_action,
}
WRITE_TOOLS = {"propose_action"}

SCHEMAS = [
    {"type": "function", "function": {"name": "get_case", "description": "The case and its alerts.",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_account_history", "description": "Account profile and recent transactions.",
        "parameters": {"type": "object", "required": ["account_id"], "properties": {
            "account_id": {"type": "string"}, "days": {"type": "integer", "default": 7}}}}},
    {"type": "function", "function": {
        "name": "expand_graph", "description": "Transfers around an account, N hops out, recent window.",
        "parameters": {"type": "object", "required": ["account_id"], "properties": {
            "account_id": {"type": "string"}, "hops": {"type": "integer", "default": 2},
            "hours": {"type": "integer", "default": 72}}}}},
    {"type": "function", "function": {
        "name": "screen_name", "description": "Fuzzy-match a person's name against the watchlist.",
        "parameters": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "search_typology", "description": "Search money-laundering typology notes.",
        "parameters": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "similar_cases", "description": "Closed cases like this one.",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "propose_action",
        "description": "Propose a next step for a human to approve. Evidence must be ids returned by tools.",
        "parameters": {"type": "object", "required": ["action", "rationale", "evidence"], "properties": {
            "action": {"type": "string", "enum": ["close", "escalate", "recommend_freeze", "file_str"]},
            "rationale": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}}}}}},
]


def as_jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o)))
