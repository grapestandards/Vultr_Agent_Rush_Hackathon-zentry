"""Training job: runs on a Vultr Training VM (cloud-init) or locally (worker subprocess).

It holds no database or storage credentials, only a short-lived job token for the Zentry API:

    GET  /train/jobs/{id}            params, champion download, artifact upload target
    GET  /train/jobs/{id}/dataset    live month + analyst labels (gzip JSON)
    POST /train/jobs/{id}/log        live log lines (→ NATS train.logs.<id> + train_runs.log_tail)
    PUT  <upload.url>                model file (pre-signed Object Storage URL, or the API itself)
    POST /train/jobs/{id}/complete   metrics + model card → model_versions (stage challenger)

    ZENTRY_API_URL=… TRAIN_RUN_ID=… TRAIN_JOB_TOKEN=… python -m zt_trainer.job
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import tempfile
import time
import traceback
from datetime import datetime

import httpx
import lightgbm as lgb
import numpy as np

from zt_core.features import FEATURES, AccountMeta, Txn
from zt_generator.generate import generate

from .dataset import build_xy, label_rows, run_engine
from .train import PARAMS, TUNABLE, caught_accounts, evaluate, fit, predict, search, tail_mask

HISTORY_SEED = 7    # last month's confirmed outcomes (same month the baseline learnt from)
HOLDOUT_SEED = 11   # an unseen month; champion and challenger are compared on exactly these rows
DAYS = 30


class Job:
    def __init__(self) -> None:
        self.run_id = os.environ["TRAIN_RUN_ID"]
        self.http = httpx.Client(base_url=os.environ["ZENTRY_API_URL"].rstrip("/"), timeout=120,
                                 headers={"Authorization": f"Bearer {os.environ['TRAIN_JOB_TOKEN']}"})
        self.t0 = time.time()

    def log(self, line: str) -> None:
        line = f"[{time.time() - self.t0:6.1f}s] {line}"
        print(line, flush=True)
        try:
            self.http.post(f"/train/jobs/{self.run_id}/log", json={"lines": [line]})
        except httpx.HTTPError:
            pass  # logs are best effort; the result is what matters

    def get(self, path: str = "") -> httpx.Response:
        r = self.http.get(f"/train/jobs/{self.run_id}{path}")
        r.raise_for_status()
        return r

    def run(self) -> None:
        spec = self.get().json()
        params = spec["params"]
        features = [f for f in params.get("features") or FEATURES if f in FEATURES]
        lgb_params = PARAMS | {k: params[k] for k in TUNABLE if params.get(k) is not None}
        where = "a Vultr Training VM" if spec["runner"] == "vultr" else "the app server"
        self.log(f"run {self.run_id} on {where} · {len(features)}/{len(FEATURES)} features · "
                 f"optuna trials={params.get('trials', 0)}")

        self.log("history month: building features…")
        X, y, _ = build_xy(generate(seed=HISTORY_SEED))
        self.log(f"  {len(y):,} rows, {int(y.sum()):,} fraud")

        sizes = [len(y)]
        if params.get("use_analyst_labels", True):
            Xl, yl = self.live_month()
            X, y = np.vstack([X, Xl]), np.concatenate([y, yl])
            sizes.append(len(yl))
        valid = tail_mask(sizes)  # last 20% of each month, so validation always holds fraud rows
        self.log(f"  validation: {int(valid.sum()):,} rows, {int(y[valid].sum()):,} fraud")

        if params.get("trials"):
            self.log(f"optuna: {params['trials']} trials on the validation split")
            lgb_params = search(X, y, lgb_params, features, int(params["trials"]), self.log, valid=valid)

        self.log("training challenger…")
        booster = fit(X, y, lgb_params, features, rounds=int(params.get("rounds", 400)), valid=valid)
        self.log(f"  best iteration {booster.best_iteration}")

        self.log("holdout month: building features…")
        Xh, yh, keys = build_xy(generate(seed=HOLDOUT_SEED))
        p_new = booster.predict(Xh[:, [FEATURES.index(f) for f in features]], num_iteration=booster.best_iteration)
        challenger = evaluate(p_new, yh, keys, DAYS)
        self.log(f"challenger: PR-AUC {challenger['pr_auc']} · mules caught {challenger['mules_caught']:.0%} · "
                 f"{challenger['alerts_per_day']} alerts/day @0.70")

        champion, gained, lost = None, [], []
        if spec.get("champion"):
            with tempfile.NamedTemporaryFile(suffix=".txt") as f:
                f.write(self.get("/champion").content)
                f.flush()
                old = lgb.Booster(model_file=f.name)
            p_old = predict(old, Xh)
            champion = evaluate(p_old, yh, keys, DAYS)
            gained = sorted(caught_accounts(p_new, yh, keys) - caught_accounts(p_old, yh, keys))
            lost = sorted(caught_accounts(p_old, yh, keys) - caught_accounts(p_new, yh, keys))
            self.log(f"champion {spec['champion']['name']}: PR-AUC {champion['pr_auc']} · mules caught "
                     f"{champion['mules_caught']:.0%} · {champion['alerts_per_day']} alerts/day @0.70")
            self.log(f"challenger catches {len(gained)} mule accounts the champion misses, misses {len(lost)}")

        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            booster.save_model(f.name, num_iteration=booster.best_iteration)
            body = open(f.name, "rb").read()
        up = spec["upload"]
        r = httpx.put(up["url"], content=body, headers=up.get("headers") or {}, timeout=120)
        r.raise_for_status()
        self.log(f"uploaded model ({len(body) / 1024:.0f} KB) → {up['artifact_key']}")

        metrics = {k: v for k, v in challenger.items() if k != "curve"}
        card = {
            "features": features, "params": {k: v for k, v in lgb_params.items() if k != "verbose"},
            "holdout": {"seed": HOLDOUT_SEED, "rows": int(len(yh)), "fraud_rows": int(yh.sum())},
            "training": {"history_seed": HISTORY_SEED, "rows": int(len(y)), "fraud_rows": int(y.sum()),
                         "analyst_labels": bool(params.get("use_analyst_labels", True))},
            "curve": challenger["curve"],
            "champion": champion and {"id": spec["champion"]["id"], "name": spec["champion"]["name"],
                                      **{k: v for k, v in champion.items()}},
            "gained_accounts": gained[:50], "lost_accounts": lost[:50],
            "seconds": round(time.time() - self.t0, 1),
        }
        self.log(f"done in {card['seconds']:.0f}s ✓ registering challenger")
        self.http.post(f"/train/jobs/{self.run_id}/complete", json={
            "metrics": metrics, "card": card, "artifact_key": up["artifact_key"]}).raise_for_status()

    def live_month(self) -> tuple[np.ndarray, np.ndarray]:
        """The ledger's own month, labelled only where an analyst decided: fraud-case accounts inside
        the case window = 1, false-positive accounts = 0, other alerted accounts left out, never
        alerted accounts = 0."""
        data = json.loads(gzip.decompress(self.get("/dataset").content))
        meta = {a: AccountMeta(datetime.fromisoformat(o), k) for a, o, k in data["accounts"]}
        txns = [Txn(i, f, t, amt, datetime.fromisoformat(ts), d) for i, f, t, amt, ts, d in data["transactions"]]
        labels = data["labels"]
        fraud = {a: (datetime.fromisoformat(s), datetime.fromisoformat(e)) for a, (s, e) in labels["fraud"].items()}
        clean, undecided = set(labels["false_positive"]), set(labels["undecided"])
        self.log(f"live month: {len(txns):,} transactions · analyst labels: {len(fraud)} fraud accounts, "
                 f"{len(clean)} false-positive accounts ({len(undecided)} undecided left out)")
        X, keys = run_engine(meta, txns)

        def is_fraud(acct: str, ts: datetime) -> bool | None:
            if acct in fraud:
                lo, hi = fraud[acct]
                return lo <= ts <= hi
            if acct in undecided:
                return None
            return False

        keep, y = label_rows(keys, is_fraud)
        self.log(f"  {len(keep):,} labelled rows, {int(y.sum()):,} fraud")
        return X[keep], y


def main() -> None:
    job = Job()
    try:
        job.run()
    except Exception as e:  # noqa: BLE001 — report every failure to the API
        job.log(f"FAILED: {e.__class__.__name__}: {e}")
        try:
            job.http.post(f"/train/jobs/{job.run_id}/fail", json={"error": traceback.format_exc()[-2000:]})
        except httpx.HTTPError:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
