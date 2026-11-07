"""Payment follow-ups (W3): a ticker picks follow-ups whose next_action_at is due and the follow-up agent
drafts the next message; jobs.followup handles "run now" and counterparty replies.

The agent only drafts. A person approves each message (API), which "sends" it to the simulated outbox
and schedules the next check. A broken promise escalates; a recon run that finds the money closes it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row

from zt_core.events import EventBus

from .agent import followup_agent

log = logging.getLogger("zt_worker.followups")

TICK_S = 30
BKK = timedelta(hours=7)


def _today():
    return (datetime.now(UTC) + BKK).date()


async def run_followups(bus: EventBus, database_url: str) -> None:
    asyncio.create_task(_ticker(database_url))
    async for batch in bus.consume("jobs.followup", durable="followup", batch=1):
        for m in batch:
            try:
                await asyncio.to_thread(process, database_url, m.data["follow_up_id"], m.data.get("reason", "due"))
                await m.ack()
            except Exception:
                log.exception("follow-up job failed: %s", m.data)
                await m.nak(delay_s=10)


async def _ticker(database_url: str) -> None:
    while True:
        try:
            async with await psycopg.AsyncConnection.connect(database_url) as conn:
                due = [r[0] for r in await (await conn.execute("""
                    select f.id from public.follow_ups f where f.stage <> 'closed' and f.next_action_at <= now()
                      and not exists (select 1 from public.messages m where m.follow_up_id = f.id and m.status = 'draft')
                    order by f.next_action_at limit 20""")).fetchall()]
            for fid in due:
                await asyncio.to_thread(process, database_url, str(fid), "due")
        except Exception:
            log.exception("follow-up tick failed")
        await asyncio.sleep(TICK_S)


def process(database_url: str, follow_up_id: str, reason: str) -> dict:
    today = _today()
    with psycopg.connect(database_url, row_factory=dict_row) as conn, conn.transaction():
        fu = conn.execute("select * from public.follow_ups where id = %s for update", (follow_up_id,)).fetchone()
        if not fu or fu["stage"] == "closed":
            return {}
        if reason == "reply":
            return _read_reply(conn, fu, today)
        if conn.execute("select 1 from public.messages where follow_up_id = %s and status = 'draft'",
                        (follow_up_id,)).fetchone():
            return {}  # a draft is already waiting for approval
        stage, level = fu["stage"], fu["level"]
        broken = stage == "promised" and fu["promise_date"] and fu["promise_date"] < today
        if fu["kind"] == "victim_refund":
            level += 1
        else:
            level = min(3, level + 1)
            if broken or level == 3:
                stage = "escalated"
        subject, body, audit = followup_agent.compose(fu, level, today)
        msg = conn.execute("""insert into public.messages (follow_up_id, channel, draft, direction, level, status,
                              subject, author) values (%s, 'email', %s, 'out', %s, 'draft', %s, %s) returning id""",
                           (follow_up_id, body, level, subject, f"agent:followup:{audit['model']}")).fetchone()["id"]
        conn.execute("""update public.follow_ups set level = %s, stage = %s, next_action_at = null, updated_at = now()
                        where id = %s""", (level, stage, follow_up_id))
        conn.execute("""insert into public.audit_log (actor, action, object_ref, before_json, after_json)
                        values (%s, 'followup:draft', %s, %s, %s)""",
                     (f"agent:followup:{audit['model']}", f"follow_up:{follow_up_id}",
                      json.dumps({"stage": fu["stage"], "level": fu["level"], "broken_promise": bool(broken)}),
                      json.dumps(audit | {"message_id": str(msg), "stage": stage, "subject": subject})))
        if level == 1 and fu["kind"] == "recon" and os.environ.get("FOLLOWUP_AUTOSEND_L1") == "1":
            conn.execute("""update public.messages set status = 'sent', sent_at = now() where id = %s""", (msg,))
            conn.execute("""update public.follow_ups set stage = 'reminded', next_action_at = now() + interval '3 days'
                            where id = %s""", (follow_up_id,))
        log.info("follow-up %s: drafted level %s (%s)", follow_up_id, level, audit["mode"])
        return {"message_id": str(msg), "level": level, "stage": stage}


def _read_reply(conn, fu: dict, today) -> dict:
    reply = conn.execute("""select id, draft from public.messages where follow_up_id = %s and direction = 'in'
                            order by created_at desc limit 1""", (fu["id"],)).fetchone()
    if not reply:
        return {}
    parsed = followup_agent.read_reply(reply["draft"], today)
    if parsed["paid"]:
        stage, promise, next_at = "promised", today, datetime.now(UTC) + timedelta(days=2)
    elif parsed["promise_date"]:
        promise = datetime.fromisoformat(parsed["promise_date"]).date()
        stage, next_at = "promised", datetime.combine(promise + timedelta(days=1), datetime.min.time(), UTC) - BKK
    else:
        stage, promise, next_at = fu["stage"], fu["promise_date"], datetime.now(UTC)
    conn.execute("""update public.follow_ups set stage = %s, promise_date = %s, next_action_at = %s, updated_at = now()
                    where id = %s""", (stage, promise, next_at, fu["id"]))
    conn.execute("update public.messages set subject = %s where id = %s", (parsed["summary"], reply["id"]))
    conn.execute("""insert into public.audit_log (actor, action, object_ref, after_json)
                    values (%s, 'followup:read_reply', %s, %s)""",
                 (f"agent:followup:{parsed['mode']}", f"follow_up:{fu['id']}",
                  json.dumps(parsed | {"reply_id": str(reply["id"]), "stage": stage})))
    return parsed
