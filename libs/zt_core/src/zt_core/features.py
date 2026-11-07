"""Streaming feature engine shared by offline training (zt_trainer) and live scoring (zt_worker).

Each transaction yields two scoring rows: one for the receiving account (money in) and one for the
sending account (money out). State is kept in memory, per account, over sliding windows; graph
features come from a periodically refreshed snapshot of the trailing 7-day transfer graph.
Transactions must be fed in timestamp order.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import networkx as nx

from .rules import Rule

DAY = timedelta(hours=24)
HOUR = timedelta(hours=1)
GRAPH_WINDOW = timedelta(days=7)

FEATURES = [
    "side_out", "amount_log", "age_days", "kyc_level", "hour",
    "in_cnt_1h", "in_amt_1h", "in_cnt_24h", "in_amt_24h",
    "out_cnt_1h", "out_amt_1h", "out_cnt_24h", "out_amt_24h", "out_in_ratio_24h",
    "senders_24h", "new_senders_24h", "receivers_24h",
    "dwell_min", "quiet_days", "device_accounts",
    "g_degree", "g_pagerank", "g_community_size",
]


@dataclass(frozen=True, slots=True)
class AccountMeta:
    opened_at: datetime
    kyc_level: int


@dataclass(slots=True)
class Txn:
    id: str
    from_account: str
    to_account: str
    amount_satang: int
    ts: datetime
    device_id: str | None


@dataclass(slots=True)
class ScoringRow:
    txn: Txn
    account_id: str
    side_out: bool
    features: dict[str, float]
    rule_hits: list[str] = field(default_factory=list)

    def vector(self) -> list[float]:
        return [self.features[f] for f in FEATURES]


def _log_baht(satang: float) -> float:
    return math.log1p(max(satang, 0) / 100)


class _Window:
    """Events (ts, amount, counterparty) of one account in one direction over the last 24h."""

    __slots__ = ("events",)

    def __init__(self) -> None:
        self.events: deque[tuple[datetime, int, str]] = deque()

    def add(self, ts: datetime, amount: int, cp: str) -> None:
        self.events.append((ts, amount, cp))

    def prune(self, now: datetime) -> None:
        while self.events and self.events[0][0] < now - DAY:
            self.events.popleft()

    def since(self, start: datetime) -> list[tuple[datetime, int, str]]:
        return [e for e in self.events if e[0] >= start]


class GraphState:
    """Trailing 7-day transfer graph; node features are recomputed by `refresh()`."""

    def __init__(self) -> None:
        self.edges: deque[tuple[datetime, str, str, int]] = deque()
        self.degree: dict[str, int] = {}
        self.pagerank: dict[str, float] = {}
        self.community_size: dict[str, int] = {}
        self.community_of: dict[str, int] = {}

    def add(self, ts: datetime, src: str, dst: str, amount: int) -> None:
        self.edges.append((ts, src, dst, amount))

    def refresh(self, now: datetime) -> None:
        while self.edges and self.edges[0][0] < now - GRAPH_WINDOW:
            self.edges.popleft()
        g = nx.DiGraph()
        for _, src, dst, amount in self.edges:
            if g.has_edge(src, dst):
                g[src][dst]["weight"] += amount
            else:
                g.add_edge(src, dst, weight=amount)
        if not g:
            return
        n = g.number_of_nodes()
        self.degree = {node: d for node, d in g.degree()}
        # Scaled so an average node is ~1 regardless of graph size.
        self.pagerank = {k: v * n for k, v in nx.pagerank(g, weight="weight", max_iter=50, tol=1e-4).items()}
        communities = nx.community.louvain_communities(g.to_undirected(), seed=7, resolution=1.0)
        self.community_size, self.community_of = {}, {}
        for i, members in enumerate(communities):
            for m in members:
                self.community_size[m] = len(members)
                self.community_of[m] = i


class FeatureEngine:
    def __init__(self, meta: dict[str, AccountMeta], rules: list[Rule] | None = None,
                 graph_refresh_every: int = 10_000) -> None:
        self.meta = meta
        self.rules = rules or []
        self.inflow: dict[str, _Window] = defaultdict(_Window)
        self.outflow: dict[str, _Window] = defaultdict(_Window)
        self.cp_first_seen: dict[str, dict[str, datetime]] = defaultdict(dict)
        self.last_activity: dict[str, datetime] = {}
        self.last_inflow: dict[str, datetime] = {}
        self.devices_of: dict[str, set[str]] = defaultdict(set)
        self.accounts_on_device: dict[str, set[str]] = defaultdict(set)
        self.graph = GraphState()
        self.graph_refresh_every = graph_refresh_every
        self._since_refresh = 0

    def process(self, t: Txn) -> list[ScoringRow]:
        """Update state with `t` and return scoring rows for its receiver and sender."""
        self._since_refresh += 1
        if self._since_refresh >= self.graph_refresh_every:
            self.graph.refresh(t.ts)
            self._since_refresh = 0

        quiet = {a: self._quiet_days(a, t.ts) for a in (t.to_account, t.from_account)}
        dwell = self._dwell_min(t.from_account, t.ts)

        # apply the transaction
        self.inflow[t.to_account].add(t.ts, t.amount_satang, t.from_account)
        self.outflow[t.from_account].add(t.ts, t.amount_satang, t.to_account)
        self.cp_first_seen[t.to_account].setdefault(t.from_account, t.ts)
        self.cp_first_seen[t.from_account].setdefault(t.to_account, t.ts)
        self.last_activity[t.to_account] = self.last_activity[t.from_account] = t.ts
        self.last_inflow[t.to_account] = t.ts
        if t.device_id:
            self.devices_of[t.from_account].add(t.device_id)
            self.accounts_on_device[t.device_id].add(t.from_account)
        self.graph.add(t.ts, t.from_account, t.to_account, t.amount_satang)

        rows = [
            ScoringRow(t, t.to_account, False, self._features(t.to_account, t, False, quiet[t.to_account], -1.0)),
            ScoringRow(t, t.from_account, True, self._features(t.from_account, t, True, quiet[t.from_account], dwell)),
        ]
        for row in rows:
            row.features["_amount_satang"] = float(t.amount_satang)
            row.rule_hits = [r.name for r in self.rules
                             if r.side_out == row.side_out and r.check(row.features, self.outflow[row.account_id])]
        return rows

    # ------------------------------------------------------------------ helpers
    def _quiet_days(self, account: str, now: datetime) -> float:
        last = self.last_activity.get(account)
        return 30.0 if last is None else min((now - last).total_seconds() / 86400, 30.0)

    def _dwell_min(self, account: str, now: datetime) -> float:
        last = self.last_inflow.get(account)
        return -1.0 if last is None else min((now - last).total_seconds() / 60, 10_080.0)

    def _features(self, account: str, t: Txn, side_out: bool, quiet_days: float, dwell: float) -> dict[str, float]:
        now = t.ts
        inw, outw = self.inflow[account], self.outflow[account]
        inw.prune(now)
        outw.prune(now)
        in_1h, out_1h = inw.since(now - HOUR), outw.since(now - HOUR)
        in_amt_24h = sum(e[1] for e in inw.events)
        out_amt_24h = sum(e[1] for e in outw.events)
        senders = {e[2] for e in inw.events}
        first_seen = self.cp_first_seen[account]
        meta = self.meta.get(account)
        devices = self.devices_of.get(account, ())
        return {
            "side_out": float(side_out),
            "amount_log": _log_baht(t.amount_satang),
            "age_days": (now - meta.opened_at).total_seconds() / 86400 if meta else 0.0,
            "kyc_level": float(meta.kyc_level) if meta else 0.0,
            "hour": float(now.hour),
            "in_cnt_1h": float(len(in_1h)),
            "in_amt_1h": _log_baht(sum(e[1] for e in in_1h)),
            "in_cnt_24h": float(len(inw.events)),
            "in_amt_24h": _log_baht(in_amt_24h),
            "out_cnt_1h": float(len(out_1h)),
            "out_amt_1h": _log_baht(sum(e[1] for e in out_1h)),
            "out_cnt_24h": float(len(outw.events)),
            "out_amt_24h": _log_baht(out_amt_24h),
            "out_in_ratio_24h": out_amt_24h / in_amt_24h if in_amt_24h else 0.0,
            "senders_24h": float(len(senders)),
            "new_senders_24h": float(sum(1 for s in senders if first_seen.get(s, now) >= now - DAY)),
            "receivers_24h": float(len({e[2] for e in outw.events})),
            "dwell_min": dwell if side_out else -1.0,
            "quiet_days": quiet_days,
            "device_accounts": float(max((len(self.accounts_on_device[d]) for d in devices), default=0)),
            "g_degree": float(self.graph.degree.get(account, 0)),
            "g_pagerank": self.graph.pagerank.get(account, 0.0),
            "g_community_size": float(self.graph.community_size.get(account, 0)),
        } | self._rule_inputs(inw, outw, now)

    @staticmethod
    def _rule_inputs(inw: _Window, outw: _Window, now: datetime) -> dict[str, float]:
        """Exact satang sums over short windows for rule thresholds. Prefixed `_`: not model features."""
        return {
            "_in_satang_60m": float(sum(e[1] for e in inw.since(now - timedelta(minutes=60)))),
            "_in_satang_24h": float(sum(e[1] for e in inw.events)),
            "_out_satang_24h": float(sum(e[1] for e in outw.events)),
            "_amount_satang": 0.0,  # filled by process()
        }


