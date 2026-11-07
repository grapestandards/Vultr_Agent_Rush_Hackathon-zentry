"""Payment follow-ups (W3): approve / edit / reject the agent's drafts, record replies, close.

Approved messages go to a simulated outbox (status 'sent'); nothing leaves the demo. Victim-refund
follow-ups are opened when an analyst closes a mule case as fraud or freezes it (W1 step 7): the
trace from each likely victim gives the amount still held in the network."""

from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from zt_core.settings import env

from .auth import User, current_user, require
from .graph import _victim_candidates, _window, trace_money

router = APIRouter(tags=["follow-ups"])

ROLES = ("collections", "finance_ops", "compliance_manager")
CADENCE = timedelta(days=3)


class ApproveIn(BaseModel):
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=8000)


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class CloseIn(BaseModel):
    reason: Literal["paid", "refunded", "written_off", "not_needed"]
    note: str = Field(default="", max_length=2000)


def _audit(conn, user: User, action: str, ref: str, before: dict | None, after: dict) -> None:
    conn.execute("""insert into public.audit_log (actor, action, object_ref, before_json, after_json)
                    values (%s, %s, %s, %s, %s)""",
                 (user.actor, action, ref, json.dumps(before, default=str) if before else None,
                  json.dumps(after, default=str)))


async def _kick(request: Request, follow_up_id: str, reason: str) -> None:
    await request.app.state.bus.publish("jobs.followup", {"follow_up_id": follow_up_id, "reason": reason},
                                        msg_id=f"followup:{follow_up_id}:{reason}:{time.time_ns()}")


@router.post("/followups/{follow_up_id}/run", status_code=202)
async def run_now(follow_up_id: str, request: Request, user: User = Depends(current_user)) -> dict:
    """Ask the agent to draft the next message now instead of waiting for next_action_at."""
    require(user, *ROLES)
    with psycopg.connect(env("DATABASE_URL")) as conn:
        if not conn.execute("select 1 from public.follow_ups where id = %s and stage <> 'closed'", (follow_up_id,)).fetchone():
            raise HTTPException(404, "open follow-up not found")
        if conn.execute("select 1 from public.messages where follow_up_id = %s and status = 'draft'", (follow_up_id,)).fetchone():
            raise HTTPException(409, "a draft is already waiting for approval")
        _audit(conn, user, "followup:run_agent", f"follow_up:{follow_up_id}", None, {})
    await _kick(request, follow_up_id, "due")
    return {"queued": True}


@router.post("/messages/{message_id}/approve")
def approve(message_id: str, body: ApproveIn, user: User = Depends(current_user)) -> dict:
    require(user, *ROLES)
    with psycopg.connect(env("DATABASE_URL"), row_factory=dict_row) as conn, conn.transaction():
        msg = conn.execute("""select m.*, f.stage, f.kind from public.messages m join public.follow_ups f
                              on f.id = m.follow_up_id where m.id = %s for update of m""", (message_id,)).fetchone()
        if not msg or msg["status"] != "draft":
            raise HTTPException(409 if msg else 404, "only drafts can be approved")
        subject, text = body.subject or msg["subject"], body.body or msg["draft"]
        conn.execute("""update public.messages set status = 'sent', sent_at = now(), approved_by = %s,
                        subject = %s, draft = %s where id = %s""", (user.id, subject, text, message_id))
        stage = "reminded" if msg["stage"] == "new" else msg["stage"]
        conn.execute("""update public.follow_ups set stage = %s, next_action_at = now() + %s, updated_at = now()
                        where id = %s""", (stage, CADENCE, msg["follow_up_id"]))
        _audit(conn, user, "message:approve_send", f"message:{message_id}",
               {"draft": msg["draft"], "subject": msg["subject"]},
               {"edited": text != msg["draft"] or subject != msg["subject"], "subject": subject,
                "outbox": "simulated inbox (demo, nothing sent)", "follow_up_stage": stage})
    return {"id": message_id, "status": "sent", "stage": stage}


@router.post("/messages/{message_id}/reject")
def reject(message_id: str, user: User = Depends(current_user)) -> dict:
    require(user, *ROLES)
    with psycopg.connect(env("DATABASE_URL"), row_factory=dict_row) as conn, conn.transaction():
        msg = conn.execute("select * from public.messages where id = %s for update", (message_id,)).fetchone()
        if not msg or msg["status"] != "draft":
            raise HTTPException(409 if msg else 404, "only drafts can be rejected")
        conn.execute("update public.messages set status = 'rejected', approved_by = %s where id = %s", (user.id, message_id))
        # step back one level so "Run agent" redrafts the same rung of the ladder
        conn.execute("""update public.follow_ups set level = greatest(level - 1, 0), updated_at = now(),
                        next_action_at = null where id = %s""", (msg["follow_up_id"],))
        _audit(conn, user, "message:reject", f"message:{message_id}", None, {"level": msg["level"]})
    return {"id": message_id, "status": "rejected"}


@router.post("/followups/{follow_up_id}/reply", status_code=202)
async def record_reply(follow_up_id: str, body: ReplyIn, request: Request, user: User = Depends(current_user)) -> dict:
    """Log the counterparty's reply; the agent reads the promise date from it."""
    require(user, *ROLES)
    with psycopg.connect(env("DATABASE_URL")) as conn:
        if not conn.execute("select 1 from public.follow_ups where id = %s and stage <> 'closed'", (follow_up_id,)).fetchone():
            raise HTTPException(404, "open follow-up not found")
        mid = conn.execute("""insert into public.messages (follow_up_id, channel, draft, direction, status, author)
                              values (%s, 'email', %s, 'in', 'received', %s) returning id""",
                           (follow_up_id, body.text, user.actor)).fetchone()[0]
        _audit(conn, user, "followup:record_reply", f"follow_up:{follow_up_id}", None, {"message_id": str(mid)})
    await _kick(request, follow_up_id, "reply")
    return {"message_id": str(mid)}


@router.post("/followups/{follow_up_id}/close")
def close(follow_up_id: str, body: CloseIn, user: User = Depends(current_user)) -> dict:
    require(user, *ROLES)
    with psycopg.connect(env("DATABASE_URL"), row_factory=dict_row) as conn, conn.transaction():
        fu = conn.execute("select * from public.follow_ups where id = %s for update", (follow_up_id,)).fetchone()
        if not fu or fu["stage"] == "closed":
            raise HTTPException(404, "open follow-up not found")
        conn.execute("""update public.follow_ups set stage = 'closed', closed_reason = %s, next_action_at = null,
                        updated_at = now() where id = %s""", (body.reason, follow_up_id))
        conn.execute("update public.messages set status = 'rejected' where follow_up_id = %s and status = 'draft'",
                     (follow_up_id,))
        _audit(conn, user, "followup:close", f"follow_up:{follow_up_id}", {"stage": fu["stage"]},
               {"reason": body.reason, "note": body.note})
    return {"id": follow_up_id, "stage": "closed"}


def open_victim_refunds(case_id: str, actor: str) -> list[str]:
    """W1 step 7: one victim_refund follow-up per likely victim whose money is still held in the network."""
    created = []
    with psycopg.connect(env("DATABASE_URL"), row_factory=dict_row) as conn:
        seeds = sorted({r["account_id"] for r in conn.execute(
            "select account_id from public.case_links where case_id = %s and account_id is not null", (case_id,))})
        if not seeds:
            return []
        start, end = _window(conn, case_id, seeds)
        start -= timedelta(days=3)
        for v in _victim_candidates(conn, seeds, start, end):
            try:
                t = trace_money(conn, v["account_id"], seeds, start, end)
            except HTTPException:
                continue
            if t["held_satang"] <= 0:
                continue
            row = conn.execute("""insert into public.follow_ups (case_id, kind, title, counterparty, contact,
                                  amount_due_satang, due_date, source_ref, next_action_at)
                                  values (%s, 'victim_refund', %s, %s, %s, %s, current_date + 14, %s, now())
                                  on conflict (kind, source_ref) where stage <> 'closed' do nothing returning id""",
                               (case_id, f"Refund held funds to {v['name_en']}", v["name_en"],
                                f"{v['account_id'].lower()}@inbox.example", t["held_satang"],
                                f"victim:{v['account_id']}")).fetchone()
            if row:
                created.append(str(row["id"]))
                conn.execute("""insert into public.audit_log (actor, action, object_ref, after_json)
                                values (%s, 'followup:open_victim_refund', %s, %s)""",
                             (actor, f"follow_up:{row['id']}",
                              json.dumps({"case_id": case_id, "victim": v["account_id"], "held_satang": t["held_satang"],
                                          "held": t["held"][:10], "paid_satang": t["paid_satang"]})))
        conn.commit()
    return created
