"""Outbox relay: publishes committed outbox rows to the EventBus in id order, then marks them sent.
At-least-once: a crash between publish and mark re-publishes, and JetStream drops the duplicate
by Nats-Msg-Id."""

from __future__ import annotations

import asyncio
import json
import logging

import psycopg

from zt_core.events import EventBus

log = logging.getLogger("zt_worker.relay")
BATCH = 1000


async def run_relay(bus: EventBus, database_url: str, idle_sleep: float = 0.2) -> None:
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=False) as conn:
        total = 0
        while True:
            async with conn.transaction():
                cur = await conn.execute(
                    """select id, subject, msg_id, payload from public.outbox
                       where published_at is null order by id limit %s for update skip locked""", (BATCH,))
                rows = await cur.fetchall()
                for _, subject, msg_id, payload in rows:
                    data = payload if isinstance(payload, dict) else json.loads(payload)
                    await bus.publish(subject, data, msg_id=msg_id)
                if rows:
                    await conn.execute("update public.outbox set published_at = now() where id = any(%s)",
                                       ([r[0] for r in rows],))
            if rows:
                total += len(rows)
                if total % 10_000 < len(rows):
                    log.info("relayed %s events", f"{total:,}")
            else:
                await asyncio.sleep(idle_sleep)
