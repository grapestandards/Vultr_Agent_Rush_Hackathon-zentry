"""Turn transactions into (X, y) by running them through the same streaming FeatureEngine the
worker uses, so training and live scoring see identical features."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

import numpy as np

from zt_core.features import FEATURES, AccountMeta, FeatureEngine, Txn
from zt_core.rules import default_rules
from zt_generator.generate import Dataset

Key = tuple[str, str, datetime]  # (transaction id, scored account, ts)


def run_engine(meta: dict[str, AccountMeta], txns: Iterable[Txn],
               graph_refresh_every: int = 10_000) -> tuple[np.ndarray, list[Key]]:
    """Feature rows (two per transaction: receiver and sender) in timestamp order."""
    engine = FeatureEngine(meta, default_rules(), graph_refresh_every)
    xs, keys = [], []
    for txn in txns:
        for row in engine.process(txn):
            xs.append(row.vector())
            keys.append((txn.id, row.account_id, txn.ts))
    return np.asarray(xs, dtype=np.float32), keys


def build_xy(ds: Dataset, graph_refresh_every: int = 10_000) -> tuple[np.ndarray, np.ndarray, list[Key]]:
    """Generated month with its ground truth: label = 1 when the scored account is a mule and the
    transaction is part of its ring's flow."""
    kyc = {c[0]: c[3] for c in ds.customers}
    meta = {a[0]: AccountMeta(a[4], kyc[a[1]]) for a in ds.accounts}
    mule = {a[0] for a in ds.accounts if a[6] == "mule"}
    fraud_txn = {t[0] for t in ds.transactions if t[8]}
    X, keys = run_engine(meta, (Txn(t[0], t[1], t[2], t[3], t[6], t[7]) for t in ds.transactions), graph_refresh_every)
    y = np.asarray([1 if (tid in fraud_txn and acct in mule) else 0 for tid, acct, _ in keys], dtype=np.int8)
    return X, y, keys


def label_rows(keys: list[Key], is_fraud: Callable[[str, datetime], bool | None]) -> tuple[np.ndarray, np.ndarray]:
    """Labels from a callback returning True / False, or None to leave the row out (undecided)."""
    keep, y = [], []
    for i, (_, acct, ts) in enumerate(keys):
        label = is_fraud(acct, ts)
        if label is not None:
            keep.append(i)
            y.append(int(label))
    return np.asarray(keep, dtype=np.int64), np.asarray(y, dtype=np.int8)


__all__ = ["FEATURES", "build_xy", "label_rows", "run_engine"]
