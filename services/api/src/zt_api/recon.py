"""Reconciliation (W2): upload settlement / bank statement files, queue a matching run, and let
Finance Ops confirm or dismiss each break's drafted journal entry. Confirming a break that is money
owed to us opens a payment follow-up (W3)."""

from __future__ import annotations

import csv
import io
import json
import re
import time
from datetime import date, timedelta
from decimal import InvalidOperation
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from zt_core import storage
from zt_core.money import baht_to_satang
from zt_core.settings import env

from .auth import User, current_user, require

router = APIRouter(prefix="/recon", tags=["recon"])

ROLES = ("finance_ops", "compliance_manager")
HEADER = ["ref_no", "counterparty_name", "amount_thb", "fee_thb", "value_date"]
MAX_BYTES = 5_000_000


class RunIn(BaseModel):
    start: date | None = None
    end: date | None = None   # inclusive; default: the whole ledger period


class UploadIn(BaseModel):
    source: Literal["bank", "gateway"]
    filename: str = Field(min_length=1, max_length=120)
    content: str = Field(max_length=MAX_BYTES)
    run: bool = True


class ResolveIn(BaseModel):
    action: Literal["confirm", "dismiss"]
    note: str = Field(default="", max_length=2000)
    follow_up: bool = True


async def _queue(request: Request, conn: psycopg.Connection, user: User, start: date | None, end: date | None) -> str:
    if conn.execute("select 1 from public.recon_runs where status in ('queued', 'running')").fetchone():
        raise HTTPException(409, "a reconciliation run is already in progress")
    if not start or not end:
        lo, hi = conn.execute("""select min((ts at time zone 'Asia/Bangkok')::date), max((ts at time zone 'Asia/Bangkok')::date)
                                 from public.transactions""").fetchone()
        if not lo:
            raise HTTPException(400, "the ledger is empty")
        start, end = start or lo, end or hi
    if end < start or (end - start).days > 92:
        raise HTTPException(422, "period must be 1–93 days")
    run_id = str(conn.execute("""insert into public.recon_runs (period, status, requested_by)
                                 values (daterange(%s, %s), 'queued', %s) returning id""",
                              (start, end + timedelta(days=1), user.id)).fetchone()[0])
    conn.execute("""insert into public.audit_log (actor, action, object_ref, after_json)
                    values (%s, 'recon:request_run', %s, %s)""",
                 (user.actor, f"recon_run:{run_id}", json.dumps({"start": str(start), "end": str(end)})))
    conn.commit()
    await request.app.state.bus.publish("jobs.recon", {"run_id": run_id}, msg_id=f"recon:{run_id}")
    return run_id


@router.post("/runs", status_code=202)
async def start_run(body: RunIn, request: Request, user: User = Depends(current_user)) -> dict:
    require(user, *ROLES)
    with psycopg.connect(env("DATABASE_URL")) as conn:
        return {"id": await _queue(request, conn, user, body.start, body.end)}


def parse_csv(text: str) -> list[tuple[str, str, int, int, date]]:
    """Gateway / bank file: ref_no, counterparty_name, amount_thb, fee_thb, value_date (YYYY-MM-DD)."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = [h.strip().lower() for h in next(reader, [])]
    if header != HEADER:
        raise HTTPException(422, f"expected columns {', '.join(HEADER)}")
    rows = []
    for n, r in enumerate(reader, start=2):
        if not any(c.strip() for c in r):
            continue
        try:
            ref, name, amount, fee, value_date = (c.strip() for c in r)
            rows.append((ref, name, baht_to_satang(amount), baht_to_satang(fee or "0"), date.fromisoformat(value_date)))
        except (ValueError, InvalidOperation) as e:
            raise HTTPException(422, f"line {n}: {e}") from None
    if not rows:
        raise HTTPException(422, "the file has no rows")
    return rows


@router.post("/upload", status_code=202)
async def upload(body: UploadIn, request: Request, user: User = Depends(current_user)) -> dict:
    """Store the raw file (Object Storage when configured), load its rows into settlements, queue a run.
    Uploading a file with the same name again replaces its rows."""
    require(user, *ROLES)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", body.filename)
    key = f"settlements/{body.source}/{name}"
    rows = parse_csv(body.content)
    stored = storage.put(key, body.content.encode())
    with psycopg.connect(env("DATABASE_URL")) as conn:
        with conn.transaction():
            referenced = conn.execute("""select count(*) from public.recon_matches m join public.settlements s
                                         on s.id = m.settlement_id where s.raw_file_key = %s""", (key,)).fetchone()[0]
            if referenced:  # earlier runs point at these rows: keep them, only add rows that are new
                existing = {r for r in conn.execute("""select ref_no, amount_satang, value_date from public.settlements
                                                       where raw_file_key = %s""", (key,))}
                rows = [r for r in rows if (r[0], r[2], r[4]) not in existing]
            else:
                conn.execute("delete from public.settlements where raw_file_key = %s", (key,))
            stamp = int(time.time() * 1000) % 10**10
            with conn.cursor().copy("""copy public.settlements (id, source, ref_no, counterparty_name, amount_satang,
                                       fee_satang, value_date, raw_file_key) from stdin""") as cp:
                for i, (ref, cp_name, amount, fee, vd) in enumerate(rows):
                    cp.write_row((f"UP{stamp:010d}-{i:05d}", body.source, ref, cp_name, amount, fee, vd, key))
            conn.execute("""insert into public.audit_log (actor, action, object_ref, after_json)
                            values (%s, 'recon:upload', %s, %s)""",
                         (user.actor, f"file:{key}", json.dumps({"rows": len(rows), "stored": stored})))
        run_id = await _queue(request, conn, user, None, None) if body.run else None
    return {"file": key, "stored": stored, "rows": len(rows), "run_id": run_id}


@router.post("/breaks/{match_id}/resolve")
def resolve(match_id: int, body: ResolveIn, user: User = Depends(current_user)) -> dict:
    require(user, *ROLES)
    with psycopg.connect(env("DATABASE_URL")) as conn, conn.transaction():
        row = conn.execute("""select break_type, resolution, journal_json, follow_up_json, transaction_id, settlement_id
                              from public.recon_matches where id = %s and break_type is not null for update""",
                           (match_id,)).fetchone()
        if not row:
            raise HTTPException(404, "break not found")
        if row[1]:
            raise HTTPException(409, f"already {row[1]}")
        resolution = "confirmed" if body.action == "confirm" else "dismissed"
        conn.execute("""update public.recon_matches set resolution = %s, resolved_by = %s, resolved_at = now(), note = %s
                        where id = %s""", (resolution, user.id, body.note or None, match_id))
        follow_up_id = None
        if resolution == "confirmed" and body.follow_up and row[3]:
            f = row[3]
            got = conn.execute("""insert into public.follow_ups (kind, title, counterparty, contact, amount_due_satang,
                                  due_date, source_ref, next_action_at)
                                  values ('recon', %s, %s, %s, %s, current_date + 7, %s, now())
                                  on conflict (kind, source_ref) where stage <> 'closed' do nothing returning id""",
                               (f["title"], f["counterparty"], f["contact"], f["amount_satang"],
                                f"{row[0]}:{row[5] or row[4]}")).fetchone()
            follow_up_id = str(got[0]) if got else None
        conn.execute("""insert into public.audit_log (actor, action, object_ref, after_json)
                        values (%s, %s, %s, %s)""",
                     (user.actor, f"recon:{body.action}_break", f"recon_match:{match_id}",
                      json.dumps({"break_type": row[0], "journal": row[2], "note": body.note,
                                  "follow_up_id": follow_up_id})))
        open_left = conn.execute("""select count(*) from public.recon_matches m join public.recon_matches me
                                    on me.run_id = m.run_id where m.id = %s and me.break_type is not null
                                    and me.resolution is null""", (match_id,)).fetchone()[0]
        if not open_left:
            conn.execute("""update public.recon_runs set status = 'done' where id =
                            (select run_id from public.recon_matches where id = %s)""", (match_id,))
    return {"id": match_id, "resolution": resolution, "follow_up_id": follow_up_id}
