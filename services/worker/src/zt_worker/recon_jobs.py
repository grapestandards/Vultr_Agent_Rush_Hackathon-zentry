"""jobs.recon consumer (W2): load ledger + settlements for the period, run the 3 matching passes,
let the recon agent explain each break and draft its journal entry, then wait for Finance Ops.

Breaks already decided in an earlier run keep their decision. Recon follow-ups whose break no longer
shows up (e.g. a late settlement has now arrived) are closed automatically (W3 step 5).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta

import psycopg

from zt_core.events import EventBus
from zt_core.recon import SCOPE_AFTER_DAYS, LedgerTxn, Settlement, reconcile, summarize

from .agent import recon_agent

log = logging.getLogger("zt_worker.recon")

FEE_BPS = 80  # contracted MDR on QR settlements


def break_key(break_type: str, transaction_id: str | None, settlement_id: str | None) -> str:
    return f"{break_type}:{settlement_id or transaction_id}"


async def run_recon_jobs(bus: EventBus, database_url: str) -> None:
    async for batch in bus.consume("jobs.recon", durable="recon", batch=1):
        for m in batch:
            await m.ack()  # a crash marks the run failed instead of redelivering
            try:
                await asyncio.to_thread(run, database_url, m.data["run_id"])
            except Exception as e:
                log.exception("recon run %s failed", m.data)
                with psycopg.connect(database_url) as conn:
                    conn.execute("""update public.recon_runs set status = 'failed', error = %s, finished_at = now()
                                    where id = %s""", (f"{e.__class__.__name__}: {e}", m.data["run_id"]))


def run(database_url: str, run_id: str) -> dict:
    with psycopg.connect(database_url) as conn:
        row = conn.execute("""update public.recon_runs set status = 'running' where id = %s and status = 'queued'
                              returning lower(period), upper(period) - 1""", (run_id,)).fetchone()
        conn.commit()
        if not row:
            return {}
        start, end = row
        ledger = [LedgerTxn(*r) for r in conn.execute("""
            select t.id, t.ref_no, t.to_account, mc.name_en, pc.name_en, t.amount_satang, t.channel,
                   (t.ts at time zone 'Asia/Bangkok')::date
            from public.transactions t
            join public.accounts m on m.id = t.to_account and m.type = 'merchant'
            join public.customers mc on mc.id = m.customer_id
            join public.accounts p on p.id = t.from_account join public.customers pc on pc.id = p.customer_id
            where t.channel in ('promptpay', 'qr')
              and t.ts >= %s::date::timestamp at time zone 'Asia/Bangkok'
              and t.ts < (%s::date + 1)::timestamp at time zone 'Asia/Bangkok'
            order by t.ts, t.id""", (start, end))]
        settlements = [Settlement(*r) for r in conn.execute("""
            select id, source, coalesce(ref_no, ''), coalesce(counterparty_name, ''), amount_satang, fee_satang, value_date
            from public.settlements where value_date between %s and %s order by value_date, id""",
            (start, end + timedelta(days=SCOPE_AFTER_DAYS)))]
        matches = reconcile(ledger, settlements, start, end, FEE_BPS)
        breaks = [m for m in matches if m.break_type]
        drafts, audit = recon_agent.explain_all(breaks)
        prior = {break_key(*r[:3]): r[3:] for r in conn.execute("""
            select distinct on (break_type, coalesce(settlement_id, transaction_id))
                   break_type, transaction_id, settlement_id, resolution, resolved_by, resolved_at, note
            from public.recon_matches where break_type is not null and resolution in ('confirmed', 'dismissed')
            order by break_type, coalesce(settlement_id, transaction_id), resolved_at desc""")}

        with conn.cursor() as cur, cur.copy("""copy public.recon_matches (run_id, transaction_id, settlement_id,
                match_rule, confidence, break_type) from stdin""") as cp:
            for m in matches:
                if not m.break_type:
                    cp.write_row((run_id, m.transaction_id, m.settlement_id, m.match_rule, m.confidence, None))
        for m, (text, journal, follow) in zip(breaks, drafts):
            res = prior.get(break_key(m.break_type, m.transaction_id, m.settlement_id), (None, None, None, None))
            conn.execute("""insert into public.recon_matches (run_id, transaction_id, settlement_id, match_rule,
                            confidence, break_type, diff_satang, explanation, journal_json, follow_up_json,
                            resolution, resolved_by, resolved_at, note)
                            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                         (run_id, m.transaction_id, m.settlement_id, m.match_rule, m.confidence, m.break_type,
                          m.diff_satang, text, json.dumps(journal) if journal else None,
                          json.dumps(follow) if follow else None, *res))

        keys = {break_key(m.break_type, m.transaction_id, m.settlement_id) for m in breaks}
        seen_ids = {i for m in matches for i in (m.transaction_id, m.settlement_id) if i}
        cleared = [fid for fid, ref in conn.execute("""select id, source_ref from public.follow_ups
                   where kind = 'recon' and stage <> 'closed'""")
                   if ref not in keys and ref.split(":", 1)[-1] in seen_ids]
        if cleared:
            conn.execute("""update public.follow_ups set stage = 'closed', closed_reason = 'cleared in reconciliation',
                            updated_at = now(), next_action_at = null where id = any(%s)""", (cleared,))
        stats = summarize(matches) | {"ledger_txns": len(ledger), "settlements": len(settlements),
                                      "auto_closed_follow_ups": len(cleared), "agent": audit["mode"]}
        conn.execute("""update public.recon_runs set status = 'review', matched_count = %s, break_count = %s,
                        stats_json = %s, finished_at = now() where id = %s""",
                     (stats["matched"], stats["breaks"], json.dumps(stats), run_id))
        conn.execute("""insert into public.audit_log (actor, action, object_ref, after_json)
                        values (%s, 'recon:run', %s, %s)""",
                     (f"agent:recon:{audit['model']}", f"recon_run:{run_id}", json.dumps(audit | {"stats": stats})))
    log.info("recon run %s: %s", run_id, stats)
    return stats
