from datetime import datetime, timedelta, timezone

from zt_core.events import shard_of, txn_subject
from zt_core.features import FEATURES, AccountMeta, FeatureEngine, Txn
from zt_core.rules import Rule, default_rules

T0 = datetime(2026, 10, 20, 10, tzinfo=timezone(timedelta(hours=7)))
META = {a: AccountMeta(T0 - timedelta(days=5), 1) for a in ["victim1", "victim2", "mule", "next", "shop"]}


def engine() -> FeatureEngine:
    return FeatureEngine(META, default_rules(), graph_refresh_every=10_000)


def test_pass_through_fires_when_money_leaves_within_minutes():
    e = engine()
    e.process(Txn("t1", "victim1", "mule", 6_000_000, T0, "d1"))
    e.process(Txn("t2", "victim2", "mule", 4_000_000, T0 + timedelta(minutes=3), "d2"))
    rows = e.process(Txn("t3", "mule", "next", 9_500_000, T0 + timedelta(minutes=9), "dm"))
    sender = next(r for r in rows if r.side_out)
    assert "pass_through" in sender.rule_hits
    assert sender.features["dwell_min"] == 6.0
    assert sender.features["out_in_ratio_24h"] == 0.95


def test_pass_through_quiet_for_slow_small_spending():
    e = engine()
    e.process(Txn("t1", "victim1", "mule", 6_000_000, T0, "d1"))
    rows = e.process(Txn("t2", "mule", "shop", 50_000, T0 + timedelta(hours=5), "dm"))
    assert "pass_through" not in next(r for r in rows if r.side_out).rule_hits


def test_vector_matches_feature_list_and_hides_rule_inputs():
    rows = engine().process(Txn("t1", "victim1", "mule", 100, T0, None))
    assert all(len(r.vector()) == len(FEATURES) for r in rows)
    assert not any(f.startswith("_") for f in FEATURES)


def test_rule_thresholds_come_from_dsl():
    strict = Rule.from_dsl({"rule": "pass_through", "params": {"window_min": 30, "ratio": 0.99, "min_in_baht": 10000}})
    e = FeatureEngine(META, [strict])
    e.process(Txn("t1", "victim1", "mule", 6_000_000, T0, None))
    rows = e.process(Txn("t2", "mule", "next", 5_700_000, T0 + timedelta(minutes=5), None))
    assert next(r for r in rows if r.side_out).rule_hits == []  # 95% < 99%


def test_shard_is_stable():
    assert shard_of("A0000001") == shard_of("A0000001")
    assert txn_subject("A0000001").startswith("txn.raw.")
