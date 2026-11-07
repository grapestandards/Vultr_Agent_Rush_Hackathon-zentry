"""Plain-language reasons for alerts, built from rule hits and top SHAP contributions."""

import math

RULE_LABEL = {
    "pass_through": "Pass-through: money out within minutes of money in",
    "fan_in_out": "Fan-in / fan-out across many accounts",
    "dormant_reactivation": "Dormant account suddenly active",
    "structuring": "Structuring just below thresholds",
    "new_account_strangers": "New account receiving from strangers",
}


def _baht(v: float) -> str:
    return f"฿{math.expm1(v):,.0f}"


FEATURE_TEXT = {
    "new_senders_24h": lambda v: f"{int(v)} first-time senders in 24h",
    "senders_24h": lambda v: f"money in from {int(v)} senders in 24h",
    "receivers_24h": lambda v: f"paid out to {int(v)} accounts in 24h",
    "out_in_ratio_24h": lambda v: f"sent on {v:.0%} of money received (24h)",
    "dwell_min": lambda v: f"money left {v:.0f} min after arriving",
    "age_days": lambda v: f"account only {v:.0f} days old",
    "device_accounts": lambda v: f"device shared by {int(v)} accounts",
    "kyc_level": lambda v: f"KYC level {int(v)}",
    "in_amt_24h": lambda v: f"{_baht(v)} received in 24h",
    "out_amt_24h": lambda v: f"{_baht(v)} sent in 24h",
    "in_amt_1h": lambda v: f"{_baht(v)} received in 1h",
    "out_amt_1h": lambda v: f"{_baht(v)} sent in 1h",
    "in_cnt_1h": lambda v: f"{int(v)} incoming transfers in 1h",
    "out_cnt_1h": lambda v: f"{int(v)} outgoing transfers in 1h",
    "in_cnt_24h": lambda v: f"{int(v)} incoming transfers in 24h",
    "out_cnt_24h": lambda v: f"{int(v)} outgoing transfers in 24h",
    "quiet_days": lambda v: f"quiet for {v:.0f} days before",
    "g_pagerank": lambda v: f"graph centrality {v:.1f}× average",
    "g_community_size": lambda v: f"part of a {int(v)}-account cluster",
    "g_degree": lambda v: f"{int(v)} counterparties in 7-day graph",
    "amount_log": lambda v: f"{_baht(v)} transfer",
    "hour": lambda v: f"at {int(v):02d}:00",
    "side_out": lambda v: "outgoing side" if v else "incoming side",
}


def reason(rule_hits: list[str], top_features: list[dict]) -> str:
    parts = [RULE_LABEL[r].split(":")[0] for r in rule_hits]
    parts += [FEATURE_TEXT[f["feature"]](f["value"]) for f in top_features
              if f["feature"] in FEATURE_TEXT
              and not (f["feature"].startswith("g_") and f["value"] == 0)]  # not yet in the graph snapshot
    return " · ".join(parts[:4])
