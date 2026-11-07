"""Train the baseline LightGBM detector.

Training data is a *different* synthetic month (generator seed 7, standing in for last month's
confirmed cases). The live dataset (seed 42) is never trained on, so the M2 detection rate is
out-of-sample.

    uv run python -m zt_trainer.baseline [--register]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_curve

from zt_core.features import FEATURES
from zt_generator.generate import generate

from .dataset import build_xy
from .train import PARAMS



def precision_at_k(y: np.ndarray, p: np.ndarray, k: int = 100) -> float:
    top = np.argsort(-p)[:k]
    return float(y[top].mean())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-seed", type=int, default=7)
    ap.add_argument("--rounds", type=int, default=300)
    ap.add_argument("--out", type=Path, default=Path("models/lgbm-baseline.txt"))
    ap.add_argument("--register", action="store_true", help="insert into model_versions as champion")
    args = ap.parse_args()

    t0 = time.time()
    ds = generate(seed=args.train_seed)
    X, y, _ = build_xy(ds)
    print(f"features: {X.shape} positives={int(y.sum())} ({time.time() - t0:.0f}s)")

    # time-ordered split: first 80% train, last 20% holdout
    cut = int(len(y) * 0.8)
    train = lgb.Dataset(X[:cut], y[:cut], feature_name=FEATURES)
    valid = lgb.Dataset(X[cut:], y[cut:], reference=train)
    booster = lgb.train(PARAMS, train, args.rounds, valid_sets=[valid],
                        callbacks=[lgb.early_stopping(30, verbose=False)])
    p = booster.predict(X[cut:])
    yh = y[cut:]
    prec, rec, thr = precision_recall_curve(yh, p)
    metrics = {
        "pr_auc": round(float(average_precision_score(yh, p)), 4),
        "precision_at_100": round(precision_at_k(yh, p, 100), 4),
        "holdout_rows": int(len(yh)),
        "holdout_positives": int(yh.sum()),
        "best_iteration": booster.best_iteration,
        "train_seed": args.train_seed,
    }
    for target in (0.5, 0.7, 0.9):
        # highest recall whose precision still meets the target
        ok = np.where(prec[:-1] >= target)[0]
        if len(ok):
            i = ok[np.argmax(rec[ok])]
            metrics[f"recall_at_precision_{target}"] = round(float(rec[i]), 4)
            metrics[f"threshold_at_precision_{target}"] = round(float(thr[i]), 4)
    print(json.dumps(metrics, indent=2))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(args.out), num_iteration=booster.best_iteration)
    card = {"name": "lgbm-baseline", "features": FEATURES, "params": PARAMS, "metrics": metrics}
    args.out.with_suffix(".card.json").write_text(json.dumps(card, indent=2))
    print(f"saved {args.out} ({time.time() - t0:.0f}s)")

    if args.register:
        import psycopg

        from zt_core.settings import env

        with psycopg.connect(env("DATABASE_URL")) as conn:
            conn.execute("update public.model_versions set stage = 'retired' where kind = 'lgbm' and stage = 'champion'")
            conn.execute("""insert into public.model_versions (kind, name, params_json, metrics_json, artifact_key,
                                                              stage, promoted_at)
                            values ('lgbm', 'lgbm-baseline', %s, %s, %s, 'champion', now())""",
                         (json.dumps(PARAMS), json.dumps(metrics), f"local:{args.out}"))
        print("registered as champion")


if __name__ == "__main__":
    main()
