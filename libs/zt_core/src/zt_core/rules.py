"""Detection scenarios. Each is configured by a `scenarios.dsl_json` row:
{"rule": "<name>", "params": {...}} — thresholds in baht/minutes/days, never code."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Protocol


class _Window(Protocol):
    def since(self, start: Any) -> list[tuple[Any, int, str]]: ...


Check = Callable[[dict[str, float], dict[str, float], _Window], bool]


def _baht(p: dict, key: str) -> float:
    return float(p[key]) * 100  # params are in baht, features in satang


def _recent(out: _Window, minutes: float) -> list[tuple[Any, int, str]]:
    events = getattr(out, "events", None)
    if not events:
        return []
    now = events[-1][0]  # the newest outflow is the transaction being scored
    return out.since(now - timedelta(minutes=minutes))


def _pass_through(f, p, out) -> bool:
    inflow = f["_in_satang_60m"]
    outflow = sum(e[1] for e in _recent(out, p["window_min"]))
    return inflow >= _baht(p, "min_in_baht") and outflow >= p["ratio"] * inflow


def _fan_in_out(f, p, _out) -> bool:
    big = max(f["_in_satang_24h"], f["_out_satang_24h"]) >= _baht(p, "min_amount_baht")
    return big and (f["senders_24h"] >= p["min_senders"] or f["receivers_24h"] >= p["min_receivers"])


def _dormant_reactivation(f, p, _out) -> bool:
    return f["quiet_days"] >= p["quiet_days"] and f["_amount_satang"] >= _baht(p, "min_in_baht")


def _structuring(f, p, out: _Window) -> bool:
    lo, hi = _baht(p, "lower_baht"), _baht(p, "upper_baht")
    return sum(1 for e in _recent(out, p["window_min"]) if lo <= e[1] < hi) >= p["min_count"]


def _new_account_strangers(f, p, _out) -> bool:
    return (f["age_days"] <= p["max_age_days"] and f["new_senders_24h"] >= p["min_new_senders"]
            and f["_in_satang_24h"] >= _baht(p, "min_in_baht"))


# name -> (scored side: True = sender/out, False = receiver/in, check)
RULES: dict[str, tuple[bool, Check]] = {
    "pass_through": (True, _pass_through),
    "fan_in_out": (False, _fan_in_out),
    "dormant_reactivation": (False, _dormant_reactivation),
    "structuring": (True, _structuring),
    "new_account_strangers": (False, _new_account_strangers),
}


@dataclass(frozen=True)
class Rule:
    name: str
    scenario_id: str | None
    side_out: bool
    params: dict[str, Any]

    def check(self, features: dict[str, float], outflow: _Window) -> bool:
        return RULES[self.name][1](features, self.params, outflow)

    @classmethod
    def from_dsl(cls, dsl: dict[str, Any], scenario_id: str | None = None) -> Rule:
        name = dsl["rule"]
        if name not in RULES:
            raise ValueError(f"unknown rule {name!r}")
        return cls(name, scenario_id, RULES[name][0], dict(dsl["params"]))


def default_rules() -> list[Rule]:
    """Same thresholds as the seeded scenarios; used offline when there is no database."""
    dsl = {
        "pass_through": {"window_min": 30, "ratio": 0.9, "min_in_baht": 10000},
        "fan_in_out": {"min_senders": 5, "min_receivers": 4, "min_amount_baht": 20000},
        "dormant_reactivation": {"quiet_days": 14, "min_in_baht": 20000},
        "structuring": {"window_min": 60, "min_count": 3, "lower_baht": 45000, "upper_baht": 50000},
        "new_account_strangers": {"max_age_days": 30, "min_new_senders": 3, "min_in_baht": 20000},
    }
    return [Rule.from_dsl({"rule": k, "params": v}) for k, v in dsl.items()]
