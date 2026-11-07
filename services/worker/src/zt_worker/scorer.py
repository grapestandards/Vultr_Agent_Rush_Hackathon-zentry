"""Scoring consumer: txn.raw.* → features (FeatureEngine) → rules + LightGBM champion → alerts.

Messages are acked only after their alerts are committed. Alerts are unique per
(transaction, account), so redelivery never duplicates them.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import psycopg

from zt_core.events import EventBus, Message
from zt_core.features import FEATURES, AccountMeta, FeatureEngine, ScoringRow, Txn
from zt_core.rules import Rule

from .cases import attach_to_cases
from .explain import reason

log = logging.getLogger("zt_worker.scorer")

ALERT_THRESHOLD = 70
RE_ALERT_AFTER = timedelta(hours=24)  # one open alert per account per day


def score_of(p: float, hits: list[str]) -> int:
    score = round(100 * p)
    if hits:  # every rule hit adds weight even when the model is unsure
        score = max(score, min(95, 50 + 15 * len(hits)))
    return score


def priority_of(score: int) -> int:
    return 1 if score >= 90 else 2 if score >= 80 else 3 if score >= 70 else 4


class Scorer:
    def __init__(self, database_url: str, model_root: Path = Path(".")) -> None:
        self.database_url = database_url
        with psycopg.connect(database_url) as conn:
            self.rules = [Rule.from_dsl(dsl, str(sid)) for sid, dsl in conn.execute(
                "select id, dsl_json from public.scenarios where status = 'active'")]
            self.scenario_ids = {r.name: r.scenario_id for r in self.rules}
            mv = conn.execute("""select id, artifact_key from public.model_versions
                                 where kind = 'lgbm' and stage = 'champion' order by created_at desc limit 1""").fetchone()
            if not mv:
                raise RuntimeError("no champion model; run `make train-baseline`")
            self.model_version_id, artifact = str(mv[0]), mv[1]
            meta = {aid: AccountMeta(opened, kyc) for aid, opened, kyc in conn.execute(
                """select a.id, a.opened_at, c.kyc_level from public.accounts a
                   join public.customers c on c.id = a.customer_id""")}
            self.last_alert: dict[str, datetime] = dict(conn.execute(
                "select account_id, max(txn_ts) from public.alerts where txn_ts is not null group by 1").fetchall())
            history = conn.execute("""select id, from_account, to_account, amount_satang, ts, device_id
                                      from public.transactions where ts > (select max(ts) - interval '7 days'
                                      from public.transactions) order by ts, id""").fetchall()
        if not artifact.startswith("local:"):
            raise RuntimeError(f"unsupported artifact {artifact}")  # Object Storage arrives with M5
        self.booster = lgb.Booster(model_file=str(model_root / artifact.removeprefix("local:")))
        self.engine = FeatureEngine(meta, self.rules)
        for row in history:  # warm the sliding windows after a restart
            self.engine.process(Txn(*row))
        log.info("scorer ready: model=%s rules=%s warm=%s txns", self.model_version_id,
                 [r.name for r in self.rules], len(history))

    def score(self, txns: list[Txn]) -> list[dict]:
        rows: list[ScoringRow] = [r for t in txns for r in self.engine.process(t)]
        if not rows:
            return []
        X = np.asarray([r.vector() for r in rows], dtype=np.float32)
        probs = self.booster.predict(X)
        contribs = self.booster.predict(X, pred_contrib=True)[:, :-1]  # SHAP values; last col is bias
        alerts = []
        for row, p, contrib in zip(rows, probs, contribs):
            s = score_of(float(p), row.rule_hits)
            if s < ALERT_THRESHOLD:
                continue
            last = self.last_alert.get(row.account_id)
            if last and row.txn.ts - last < RE_ALERT_AFTER:
                continue
            self.last_alert[row.account_id] = row.txn.ts
            top = [{"feature": FEATURES[i], "value": round(float(row.features[FEATURES[i]]), 3),
                    "contribution": round(float(contrib[i]), 3)}
                   for i in np.argsort(-contrib)[:3] if contrib[i] > 0]
            alerts.append({
                "transaction_id": row.txn.id, "account_id": row.account_id,
                "scenario_id": self.scenario_ids.get(row.rule_hits[0]) if row.rule_hits else None,
                "model_version": self.model_version_id, "score": s, "priority": priority_of(s),
                "top_features_json": json.dumps(top), "rule_hits": row.rule_hits,
                "reason": reason(row.rule_hits, top), "txn_ts": row.txn.ts,
            })
        return alerts


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
