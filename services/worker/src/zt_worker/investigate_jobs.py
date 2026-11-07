"""jobs.investigate consumer: runs the Investigator for a case (from the case builder or the API)."""

from __future__ import annotations

import asyncio
import logging

import psycopg

from zt_core.events import EventBus

from .agent.investigator import investigate

log = logging.getLogger("zt_worker.investigate_jobs")


async def run_investigator(bus: EventBus, database_url: str) -> None:
    async for batch in bus.consume("jobs.investigate", durable="investigator", batch=1):
        for m in batch:
            try:
                if not m.data.get("force") and not await _needs_run(database_url, m.data["case_id"]):
                    await m.ack()
                    continue
                await asyncio.to_thread(investigate, database_url, m.data["case_id"])
                await m.ack()
            except Exception:
                log.exception("investigation failed for %s", m.data)
                await m.nak(delay_s=10)


async def _needs_run(database_url: str, case_id: str) -> bool:
    """Skip deleted (merged) cases and cases unchanged since their last investigation."""
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        cur = await conn.execute("""select investigated_at is null or updated_at > investigated_at
                                    from public.cases where id = %s and status <> 'closed'""", (case_id,))
        row = await cur.fetchone()
    return bool(row and row[0])
