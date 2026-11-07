"""Case actions: queue an AI investigation, record the analyst's decision (W1 step 6).
Every decision is audited with before/after state and becomes the case's label for model tuning."""

from __future__ import annotations

import json
import time
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from zt_core.settings import env

from .auth import User, current_user, require

router = APIRouter(prefix="/cases", tags=["cases"])

Decision = Literal["close_false_positive", "close_fraud", "escalate", "freeze"]

# decision -> (case status, disposition, proposal action it accepts)
EFFECTS: dict[str, tuple[str, str | None, str]] = {
    "close_false_positive": ("closed", "false_positive", "close"),
    "close_fraud": ("closed", "fraud", "file_str"),
    "escalate": ("escalated", None, "escalate"),
    "freeze": ("escalated", "fraud", "recommend_freeze"),
}


class DecisionIn(BaseModel):
    decision: Decision
    note: str = Field(default="", max_length=2000)
    accounts: list[str] | None = Field(default=None, description="accounts to freeze; default: all alerted in case")
    str_text: str | None = Field(default=None, max_length=20_000)
    approve_str: bool = False


@router.post("/{case_id}/investigate", status_code=202)
async def queue_investigation(case_id: str, request: Request, user: User = Depends(current_user)) -> dict:
    require(user, "analyst", "compliance_manager")
    with psycopg.connect(env("DATABASE_URL")) as conn:
        if not conn.execute("select 1 from public.cases where id = %s", (case_id,)).fetchone():
            raise HTTPException(404, "case not found")
        conn.execute("""insert into public.audit_log (actor, action, object_ref) values (%s, 'request_investigation', %s)""",
                     (user.actor, f"case:{case_id}"))
    await request.app.state.bus.publish("jobs.investigate", {"case_id": case_id, "force": True},
                                        msg_id=f"investigate:{case_id}:{int(time.time())}")
    return {"queued": True}


@router.post("/{case_id}/decision")
def decide(case_id: str, body: DecisionIn, user: User = Depends(current_user)) -> dict:
    require(user, "analyst", "compliance_manager")
    status, disposition, accepted_action = EFFECTS[body.decision]
    with psycopg.connect(env("DATABASE_URL")) as conn, conn.transaction():
        before = conn.execute("""select status, disposition, str_draft, str_approved_at from public.cases
                                 where id = %s for update""", (case_id,)).fetchone()
        if not before:
            raise HTTPException(404, "case not found")
        alerted = [r[0] for r in conn.execute("""select distinct a.account_id from public.case_links l
                   join public.alerts a on a.id = l.alert_id where l.case_id = %s""", (case_id,))]
        frozen: list[str] = []
        if body.decision == "freeze":
            targets = body.accounts or alerted
            outside = sorted(set(targets) - set(alerted))
            if outside:
                raise HTTPException(400, f"accounts not in this case: {outside}")
            frozen = [r[0] for r in conn.execute("""update public.accounts set status = 'frozen'
                      where id = any(%s) and status = 'active' returning id""", (targets,))]
        str_text = body.str_text if body.str_text is not None else before[2]
        conn.execute("""update public.cases set status = %s, disposition = coalesce(%s, disposition),
                        assignee = %s, str_draft = %s, updated_at = now(),
                        str_approved_by = case when %s then %s::uuid else str_approved_by end,
                        str_approved_at = case when %s then now() else str_approved_at end
                        where id = %s""",
                     (status, disposition, user.id, str_text, body.approve_str, user.id, body.approve_str, case_id))
        if status == "closed":
            conn.execute("""update public.alerts set status = 'closed' where id in
                            (select alert_id from public.case_links where case_id = %s and alert_id is not null)""",
                         (case_id,))
        conn.execute("""update public.case_proposals set status = case when action = %s then 'accepted' else 'rejected' end,
                        decided_by = %s, decided_at = now() where case_id = %s and status = 'pending'""",
                     (accepted_action, user.id, case_id))
        after = {"status": status, "disposition": disposition or before[1], "frozen_accounts": frozen,
                 "str_approved": body.approve_str, "note": body.note}
        conn.execute("""insert into public.audit_log (actor, action, object_ref, before_json, after_json)
                        values (%s, %s, %s, %s, %s)""",
                     (user.actor, f"decision:{body.decision}", f"case:{case_id}",
                      json.dumps({"status": before[0], "disposition": before[1], "str_approved": before[3] is not None}),
                      json.dumps(after)))
    return {"case_id": case_id, **after}
