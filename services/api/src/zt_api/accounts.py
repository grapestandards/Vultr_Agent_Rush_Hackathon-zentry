"""Account entity page (Arkham-style profile) and the audited PII reveal.

Names are masked everywhere ("Somying Sd****"); merchants keep their business name. The full name is
returned only by POST /pii/reveal, with a reason, and every reveal is written to audit_log."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from zt_core.settings import env

from .auth import User, current_user, require

router = APIRouter(tags=["accounts"])

READ_ROLES = ("analyst", "compliance_manager", "finance_ops", "collections")
REVEAL_ROLES = ("analyst", "compliance_manager", "collections")


class RevealIn(BaseModel):
    account_id: str = Field(min_length=2, max_length=32)
    reason: str = Field(min_length=5, max_length=500)


@router.get("/accounts/{account_id}/entity")
def entity(account_id: str, user: User = Depends(current_user)) -> dict:
    require(user, *READ_ROLES)
    with psycopg.connect(env("DATABASE_URL"), row_factory=dict_row) as conn:
        prof = conn.execute("""
            select a.id, a.type, a.status, a.bank_code, a.opened_at, c.display_en as name, c.display_th as name_th,
                   c.kyc_level, c.created_at as customer_since,
                   (select count(*) from public.accounts o where o.customer_id = a.customer_id) as accounts_held,
                   (select count(distinct t.device_id) from public.transactions t
                     where t.from_account = a.id and t.device_id is not null) as devices
            from public.accounts a join public.customers c on c.id = a.customer_id where a.id = %s""",
                            (account_id,)).fetchone()
        if not prof:
            raise HTTPException(404, "account not found")
        alerts = conn.execute("""select count(*) as n, max(score) as max_score, array_agg(distinct r) filter (where r is not null) as rules
                                 from public.alerts al left join lateral unnest(al.rule_hits) r on true
                                 where al.account_id = %s""", (account_id,)).fetchone()
        cases = conn.execute("""select distinct k.id::text, k.status, k.disposition, k.risk_level, k.title
                                from public.case_links l join public.cases k on k.id = l.case_id
                                where l.account_id = %s or l.alert_id in
                                  (select id from public.alerts where account_id = %s)""", (account_id, account_id)).fetchall()
        txns = conn.execute("""
            select t.id, t.from_account, t.to_account, t.amount_satang, t.channel, t.ts, t.device_id
            from public.transactions t where t.from_account = %(a)s or t.to_account = %(a)s
            order by t.ts""", {"a": account_id}).fetchall()
        others = {t["to_account"] if t["from_account"] == account_id else t["from_account"] for t in txns}
        names = {r["id"]: r for r in conn.execute("""
            select a.id, a.type, c.display_en as name,
                   (select max(score) from public.alerts al where al.account_id = a.id) as risk
            from public.accounts a join public.customers c on c.id = a.customer_id where a.id = any(%s)""",
                                                    (list(others),))}

    # daily balance history (running net flow; synthetic data has no opening balance)
    daily: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    cps: dict[str, dict] = {}
    for t in txns:
        out = t["from_account"] == account_id
        day = (t["ts"] + timedelta(hours=7)).date().isoformat()
        daily[day][1 if out else 0] += t["amount_satang"]
        other = t["to_account"] if out else t["from_account"]
        cp = cps.setdefault(other, {"account_id": other, "in_satang": 0, "out_satang": 0, "count": 0,
                                    **{k: names.get(other, {}).get(k) for k in ("name", "type", "risk")}})
        cp["out_satang" if out else "in_satang"] += t["amount_satang"]
        cp["count"] += 1
    balance, history = 0, []
    for day in sorted(daily):
        inflow, outflow = daily[day]
        balance += inflow - outflow
        history.append({"day": day, "in_satang": inflow, "out_satang": outflow, "balance_satang": balance})

    labels = [prof["type"]]
    if prof["status"] == "frozen":
        labels.append("frozen")
    if alerts["n"]:
        labels.append(f"risk {alerts['max_score']}")
    labels += [f"rule: {r}" for r in sorted(alerts["rules"] or [])]
    if any(c["disposition"] == "fraud" for c in cases):
        labels.append("confirmed fraud")
    recent = []
    for t in reversed(txns[-150:]):
        out = t["from_account"] == account_id
        other = t["to_account"] if out else t["from_account"]
        recent.append({**t, "direction": "out" if out else "in", "counterparty": other,
                       "counterparty_name": names.get(other, {}).get("name"),
                       "counterparty_risk": names.get(other, {}).get("risk"),
                       "device_id": _mask_device(t["device_id"])})
    return {
        "profile": {**prof, "labels": labels, "alerts": alerts["n"], "max_score": alerts["max_score"]},
        "stats": {"in_satang": sum(h["in_satang"] for h in history), "out_satang": sum(h["out_satang"] for h in history),
                  "transfers": len(txns), "counterparties": len(cps),
                  "first_seen": txns[0]["ts"] if txns else None, "last_seen": txns[-1]["ts"] if txns else None},
        "cases": cases,
        "history": history,
        "counterparties": sorted(cps.values(), key=lambda c: -(c["in_satang"] + c["out_satang"]))[:25],
        "transfers": recent,
    }


def _mask_device(device: str | None) -> str | None:
    return f"{device[:6]}****" if device and len(device) > 6 else device


@router.post("/pii/reveal")
def reveal(body: RevealIn, user: User = Depends(current_user)) -> dict:
    """Full name of an account holder, for a stated reason. Every reveal is audited."""
    require(user, *REVEAL_ROLES)
    with psycopg.connect(env("DATABASE_URL"), row_factory=dict_row) as conn:
        row = conn.execute("""select c.name_en, c.name_th, c.display_en from public.accounts a
                              join public.customers c on c.id = a.customer_id where a.id = %s""",
                           (body.account_id,)).fetchone()
        if not row:
            raise HTTPException(404, "account not found")
        conn.execute("""insert into public.audit_log (actor, action, object_ref, after_json)
                        values (%s, 'pii:reveal', %s, %s)""",
                     (user.actor, f"account:{body.account_id}",
                      json.dumps({"reason": body.reason, "role": user.role, "fields": ["name_en", "name_th"]})))
    return {"account_id": body.account_id, "name_en": row["name_en"], "name_th": row["name_th"]}
