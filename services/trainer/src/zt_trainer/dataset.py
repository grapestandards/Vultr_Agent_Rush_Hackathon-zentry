"""Turn a generated dataset into (X, y) by running it through the same streaming FeatureEngine the
worker uses, so training and live scoring see identical features."""

from __future__ import annotations

import numpy as np

from zt_core.features import FEATURES, AccountMeta, FeatureEngine, Txn
from zt_core.rules import default_rules
from zt_generator.generate import Dataset


def build_xy(ds: Dataset, graph_refresh_every: int = 10_000) -> tuple[np.ndarray, np.ndarray, list[tuple]]:
    """Label = 1 when the scored account is a mule and the transaction is part of its ring's flow."""
    meta = {a[0]: AccountMeta(a[4], 0) for a in ds.accounts}
    kyc = {c[0]: c[3] for c in ds.customers}
    meta = {a[0]: AccountMeta(a[4], kyc[a[1]]) for a in ds.accounts}
    mule = {a[0] for a in ds.accounts if a[6] == "mule"}
    engine = FeatureEngine(meta, default_rules(), graph_refresh_every)
    xs, ys, keys = [], [], []
    for t in ds.transactions:
        txn = Txn(t[0], t[1], t[2], t[3], t[6], t[7])
        for row in engine.process(txn):
            xs.append(row.vector())
            ys.append(1 if (t[8] and row.account_id in mule) else 0)
            keys.append((t[0], row.account_id, row.rule_hits))
    return np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.int8), keys


__all__ = ["FEATURES", "build_xy"]
