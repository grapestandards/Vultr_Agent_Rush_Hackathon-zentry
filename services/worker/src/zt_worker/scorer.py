"""Scoring consumer: txn.raw.* → features (FeatureEngine) → rules + LightGBM champion → alerts.

Messages are acked only after their alerts are committed. Alerts are unique per
(transaction, account), so redelivery never duplicates them.

The champion (and an optional shadow model) are re-read from model_versions every few seconds,
so Promote / Rollback in the Tuning page take effect without a restart. A shadow model scores the
same rows but never raises alerts; its would-be alert counts are written to shadow_json.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import psycopg

from zt_core import storage
from zt_core.events import EventBus, Message
from zt_core.features import FEATURES, AccountMeta, FeatureEngine, ScoringRow, Txn
from zt_core.rules import Rule

from .cases import attach_to_cases
from .explain import reason

log = logging.getLogger("zt_worker.scorer")

ALERT_THRESHOLD = 70  # default; a model's params_json.alert_threshold overrides it
RE_ALERT_AFTER = timedelta(hours=24)  # one open alert per account per day
RELOAD_EVERY_S = 5
SHADOW_FLUSH_S = 15


def score_of(p: float, hits: list[str]) -> int:
    score = round(100 * p)
    if hits:  # every rule hit adds weight even when the model is unsure
        score = max(score, min(95, 50 + 15 * len(hits)))
    return score


def priority_of(score: int) -> int:
    return 1 if score >= 90 else 2 if score >= 80 else 3 if score >= 70 else 4


@dataclass
class LoadedModel:
    id: str
    booster: lgb.Booster
    features: list[str]      # the model's own feature list (feature toggles in Tuning)
    threshold: int
    cols: list[int] = field(init=False)

    def __post_init__(self) -> None:
        self.cols = [FEATURES.index(f) for f in self.features]

    @classmethod
    def load(cls, model_id: str, artifact_key: str, params: dict, model_root: Path) -> LoadedModel:
        if artifact_key.startswith("local:"):
            path = model_root / artifact_key.removeprefix("local:")
        else:
            path = storage.fetch(artifact_key)
        booster = lgb.Booster(model_file=str(path))
        return cls(model_id, booster, booster.feature_name(), int(params.get("alert_threshold") or ALERT_THRESHOLD))


class Scorer:
    def __init__(self, database_url: str, model_root: Path = Path(".")) -> None:
        self.database_url = database_url
        self.model_root = model_root
        self.champion: LoadedModel | None = None
        self.shadow: LoadedModel | None = None
        self.shadow_stats: dict[str, int] = {}
        self._checked = self._flushed = 0.0
        with psycopg.connect(database_url) as conn:
            self.rules = [Rule.from_dsl(dsl, str(sid)) for sid, dsl in conn.execute(
                "select id, dsl_json from public.scenarios where status = 'active'")]
            self.scenario_ids = {r.name: r.scenario_id for r in self.rules}
            self.refresh_models(conn)
            if not self.champion:
                raise RuntimeError("no champion model; run `make train-baseline`")
            meta = {aid: AccountMeta(opened, kyc) for aid, opened, kyc in conn.execute(
                """select a.id, a.opened_at, c.kyc_level from public.accounts a
                   join public.customers c on c.id = a.customer_id""")}
            self.last_alert: dict[str, datetime] = dict(conn.execute(
                "select account_id, max(txn_ts) from public.alerts where txn_ts is not null group by 1").fetchall())
            history = conn.execute("""select id, from_account, to_account, amount_satang, ts, device_id
                                      from public.transactions where ts > (select max(ts) - interval '7 days'
                                      from public.transactions) order by ts, id""").fetchall()
        self.engine = FeatureEngine(meta, self.rules)
        for row in history:  # warm the sliding windows after a restart
            self.engine.process(Txn(*row))
        log.info("scorer ready: model=%s rules=%s warm=%s txns", self.champion.id,
                 [r.name for r in self.rules], len(history))

    @property
    def model_version_id(self) -> str:
        return self.champion.id

    def refresh_models(self, conn) -> None:
        """Pick up Promote / Rollback / Shadow changes; logs each newly loaded model to audit_log."""
        rows = {stage: (str(i), key, params) for stage, i, key, params in conn.execute(
            """select stage, id, artifact_key, params_json from public.model_versions
               where kind = 'lgbm' and stage in ('champion', 'shadow')""")}
        for stage in ("champion", "shadow"):
            row, current = rows.get(stage), getattr(self, stage)
            if row is None:
                setattr(self, stage, None)
                continue
            threshold = int(row[2].get("alert_threshold") or ALERT_THRESHOLD)
            if current and current.id == row[0] and current.threshold == threshold:
                continue
            setattr(self, stage, LoadedModel.load(*row, self.model_root))
            if stage == "shadow":
                self.shadow_stats = {"rows": 0, "would_alert": 0, "champion_alerts": 0, "both": 0}
            conn.execute("""insert into public.audit_log (actor, action, object_ref, after_json)
                            values ('service:scorer', %s, %s, %s)""",
                         (f"model:loaded_{stage}", f"model:{row[0]}", json.dumps({"threshold": threshold})))
            conn.commit()
            log.info("loaded %s model %s (threshold %s)", stage, row[0], threshold)
        self._checked = time.time()

    def maybe_refresh(self) -> None:
        now = time.time()
        if now - self._checked < RELOAD_EVERY_S and now - self._flushed < SHADOW_FLUSH_S:
            return
        with psycopg.connect(self.database_url) as conn:
            if now - self._flushed >= SHADOW_FLUSH_S:
                self._flushed = now
                if self.shadow and self.shadow_stats.get("rows"):
                    conn.execute("update public.model_versions set shadow_json = %s where id = %s",
                                 (json.dumps(self.shadow_stats | {"updated_at": datetime.now().isoformat()}),
                                  self.shadow.id))
                    conn.commit()
            if now - self._checked >= RELOAD_EVERY_S:
                self.refresh_models(conn)

    def score(self, txns: list[Txn]) -> list[dict]:
        rows: list[ScoringRow] = [r for t in txns for r in self.engine.process(t)]
        if not rows:
            return []
        champ = self.champion
        X = np.asarray([r.vector() for r in rows], dtype=np.float32)
        probs = champ.booster.predict(X[:, champ.cols])
        contribs = champ.booster.predict(X[:, champ.cols], pred_contrib=True)[:, :-1]  # SHAP; last col is bias
        if self.shadow:
            self._shadow(rows, X, probs)
        alerts = []
        for row, p, contrib in zip(rows, probs, contribs):
            s = score_of(float(p), row.rule_hits)
            if s < champ.threshold:
                continue
            last = self.last_alert.get(row.account_id)
            if last and row.txn.ts - last < RE_ALERT_AFTER:
                continue
            self.last_alert[row.account_id] = row.txn.ts
            top = [{"feature": champ.features[i], "value": round(float(row.features[champ.features[i]]), 3),
                    "contribution": round(float(contrib[i]), 3)}
                   for i in np.argsort(-contrib)[:3] if contrib[i] > 0]
            alerts.append({
                "transaction_id": row.txn.id, "account_id": row.account_id,
                "scenario_id": self.scenario_ids.get(row.rule_hits[0]) if row.rule_hits else None,
                "model_version": champ.id, "score": s, "priority": priority_of(s),
                "top_features_json": json.dumps(top), "rule_hits": row.rule_hits,
                "reason": reason(row.rule_hits, top), "txn_ts": row.txn.ts,
            })
        return alerts

    def _shadow(self, rows: list[ScoringRow], X: np.ndarray, champ_probs: np.ndarray) -> None:
        sh, st = self.shadow, self.shadow_stats
        for row, p_new, p_old in zip(rows, sh.booster.predict(X[:, sh.cols]), champ_probs):
            new = score_of(float(p_new), row.rule_hits) >= sh.threshold
            old = score_of(float(p_old), row.rule_hits) >= self.champion.threshold
            st["rows"] += 1
            st["would_alert"] += new
            st["champion_alerts"] += old
            st["both"] += new and old


def txn_from(data: dict) -> Txn:
    return Txn(data["id"], data["from_account"], data["to_account"], int(data["amount_satang"]),
               datetime.fromisoformat(data["ts"]), data.get("device_id"))


async def run_scorer(bus: EventBus, database_url: str, model_root: Path) -> None:
    scorer = Scorer(database_url, model_root)
    cols = ["transaction_id", "account_id", "scenario_id", "model_version", "score", "priority",
            "top_features_json", "rule_hits", "reason", "txn_ts"]
    done, t0 = 0, time.time()
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        async for batch in bus.consume("txn.raw.*", durable="scorer"):
            try:
                scorer.maybe_refresh()
            except Exception:
                log.exception("model refresh failed; keeping the loaded models")
            if not batch:
                continue
            try:
                alerts = scorer.score([txn_from(m.data) for m in batch])
                new_cases: list[str] = []
                if alerts:
                    async with conn.transaction():
                        async with conn.cursor() as cur:
                            ids = []
                            for a in alerts:
                                await cur.execute(
                                    f"""insert into public.alerts ({', '.join(cols)})
                                        values ({', '.join(['%s'] * len(cols))})
                                        on conflict (transaction_id, account_id) do nothing returning id""",
                                    [a[c] for c in cols])
                                if row := await cur.fetchone():
                                    ids.append(row[0])
                            new_cases = await attach_to_cases(cur, ids)
                    for case_id in new_cases:  # the investigator skips cases unchanged since its last run
                        await bus.publish("jobs.investigate", {"case_id": case_id})
                    for a in alerts:
                        await bus.publish("alerts.new", {k: a[k] for k in ("transaction_id", "account_id", "score")},
                                          msg_id=f"alert:{a['transaction_id']}:{a['account_id']}")
            except Exception:
                log.exception("scoring batch failed")
                await _retry_or_dead_letter(bus, batch)
                continue
            for m in batch:
                await m.ack()
            done += len(batch)
            if done % 10_000 < len(batch):
                log.info("scored %s txns (%.0f/s), +%d alerts", f"{done:,}", done / (time.time() - t0), len(alerts))


async def _retry_or_dead_letter(bus: EventBus, batch: list[Message]) -> None:
    from zt_core.events import MAX_DELIVER

    for m in batch:
        if m.deliveries >= MAX_DELIVER - 1:
            await bus.publish("txn.dlq", m.data, msg_id=f"dlq:{m.msg_id}")
            await m.ack()
        else:
            await m.nak(delay_s=2)
