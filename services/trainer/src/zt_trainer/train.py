"""LightGBM training, Optuna search and holdout evaluation shared by the baseline and training jobs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import lightgbm as lgb
import numpy as np
from sklearn.metrics import average_precision_score

from zt_core.features import FEATURES

PARAMS = {
    "objective": "binary", "learning_rate": 0.05, "num_leaves": 31, "min_data_in_leaf": 50,
    "feature_fraction": 0.9, "bagging_fraction": 0.8, "bagging_freq": 1, "scale_pos_weight": 20,
    "verbose": -1, "seed": 7,
}
TUNABLE = ("learning_rate", "num_leaves", "min_data_in_leaf", "feature_fraction", "scale_pos_weight")
THRESHOLDS = [round(t, 2) for t in np.arange(0.05, 1.0, 0.05)]


def columns(features: list[str]) -> list[int]:
    return [FEATURES.index(f) for f in features]


def fit(X: np.ndarray, y: np.ndarray, params: dict, features: list[str], rounds: int = 400) -> lgb.Booster:
    """Time-ordered split: the last 20% of rows choose the number of rounds (early stopping)."""
    cut = int(len(y) * 0.8)
    cols = columns(features)
    train = lgb.Dataset(X[:cut, cols], y[:cut], feature_name=features)
    valid = lgb.Dataset(X[cut:, cols], y[cut:], reference=train)
    return lgb.train(params, train, rounds, valid_sets=[valid], callbacks=[lgb.early_stopping(30, verbose=False)])


def search(X: np.ndarray, y: np.ndarray, base: dict, features: list[str], trials: int,
           log: Callable[[str], None]) -> dict:
    """Optuna over the tunable params, scored by validation PR-AUC."""
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    cut = int(len(y) * 0.8)
    cols = columns(features)

    def objective(trial: optuna.Trial) -> float:
        params = base | {
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.2, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 15, 127, log=True),
            "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 20, 200, log=True),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.6, 1.0),
            "scale_pos_weight": trial.suggest_float("scale_pos_weight", 1, 50, log=True),
        }
        b = fit(X, y, params, features, rounds=300)
        score = float(average_precision_score(y[cut:], b.predict(X[cut:, cols], num_iteration=b.best_iteration)))
        log(f"  trial {trial.number + 1}/{trials}: PR-AUC {score:.4f} "
            f"(lr={params['learning_rate']:.3f}, leaves={params['num_leaves']}, spw={params['scale_pos_weight']:.1f})")
        return score

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=7))
    study.optimize(objective, n_trials=trials)
    log(f"best trial: PR-AUC {study.best_value:.4f}")
    return base | study.best_params


def predict(booster: lgb.Booster, X: np.ndarray) -> np.ndarray:
    return booster.predict(X[:, columns(booster.feature_name())])


def evaluate(p: np.ndarray, y: np.ndarray, keys: list[tuple[str, str, datetime]], days: float) -> dict:
    """Row-level PR-AUC / precision@100 plus, per threshold, what an analyst would see: alerts per
    day (one per account per day, like the scorer) and the share of mule accounts caught."""
    order = np.argsort(-p)
    accounts = np.asarray([k[1] for k in keys])
    day = np.asarray([k[2].date().toordinal() for k in keys])
    mules = set(accounts[y == 1])
    curve = []
    for thr in THRESHOLDS:
        hit = p >= thr
        tp = int((hit & (y == 1)).sum())
        flagged = set(accounts[hit])
        curve.append({
            "threshold": thr,
            "precision": round(tp / max(int(hit.sum()), 1), 4),
            "recall": round(tp / max(int(y.sum()), 1), 4),
            "alerts_per_day": round(len(set(zip(accounts[hit], day[hit]))) / days, 1),
            "mules_caught": round(len(flagged & mules) / max(len(mules), 1), 4),
            "clean_accounts_flagged": len(flagged - mules),
        })
    at = next(c for c in curve if c["threshold"] == 0.7)
    return {
        "pr_auc": round(float(average_precision_score(y, p)), 4),
        "precision_at_100": round(float(y[order[:100]].mean()), 4),
        "recall": at["recall"], "alerts_per_day": at["alerts_per_day"], "mules_caught": at["mules_caught"],
        "curve": curve,
    }


def caught_accounts(p: np.ndarray, y: np.ndarray, keys: list, thr: float = 0.7) -> set[str]:
    """Mule accounts (in the holdout) with at least one fraud row scored above the threshold."""
    return {keys[i][1] for i in np.where((p >= thr) & (y == 1))[0]}
