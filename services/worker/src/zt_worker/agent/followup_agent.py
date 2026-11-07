"""Follow-up agent (W3 step 2): pick the next message on the reminder ladder and draft it in Thai + English.

Levels: 1 friendly reminder, 2 firm reminder with a deadline, 3 escalation notice (a human takes over).
Victim-refund follow-ups get progress updates instead of reminders. Drafts are never sent by the agent;
a person approves each one (the outbox is a simulated inbox in the demo). The LLM, when configured,
rewrites the template; its text may cite only the references in the follow-up's facts.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

from zt_core.money import format_thb

from . import llm

SYSTEM = """You draft payment follow-up messages for a Thai e-wallet's finance team. All data is synthetic.
Write a short, polite, professional message: Thai first, then English. Keep every amount and reference exactly
as given. Do not promise anything not in the facts. Level 1 = friendly reminder, 2 = firm with a deadline,
3 = escalation notice. Return JSON: {"subject": str, "body": str}"""


def draft(fu: dict, level: int, today: date) -> tuple[str, str]:
    amt, ref, who = format_thb(fu["amount_due_satang"]), fu.get("source_ref") or "", fu["counterparty"]
    ref = ref.split(":", 1)[-1]
    if fu["kind"] == "victim_refund":
        subject = f"ความคืบหน้าการคืนเงิน / Refund update — case {str(fu['case_id'])[:8]}"
        body = (f"เรียน คุณ{who}\n\nเราตรวจพบว่าเงินของท่านจำนวน {amt} ยังคงอยู่ในบัญชีที่ถูกระงับไว้ "
                "ขณะนี้อยู่ระหว่างขั้นตอนตรวจสอบเพื่อคืนเงิน เราจะแจ้งความคืบหน้าอีกครั้งภายใน 3 วันทำการ\n\n"
                f"Dear {who},\n\nWe have identified {amt} of your funds still held in accounts that are now restricted. "
                "The refund is being processed; we will update you again within 3 business days.\n\n— Zentry Payments Team")
        return subject, body
    deadline = today + timedelta(days=7 if level == 1 else 3)
    if level <= 1:
        subject = f"แจ้งยอดค้างชำระ / Payment reminder — {ref}"
        body = (f"เรียน {who}\n\nจากการกระทบยอดพบรายการ {ref} ยอด {amt} ที่ยังไม่ได้รับชำระ "
                f"รบกวนตรวจสอบและโอนชำระภายในวันที่ {deadline:%d/%m/%Y} หากชำระแล้วโปรดแจ้งเลขอ้างอิงกลับมา\n\n"
                f"Dear {who},\n\nOur reconciliation shows {amt} outstanding on {ref}. Please review and settle by "
                f"{deadline:%d %b %Y}. If already paid, kindly reply with the payment reference.\n\n— Zentry Finance Ops")
    elif level == 2:
        subject = f"แจ้งเตือนครั้งที่ 2 / Second reminder — {ref}"
        body = (f"เรียน {who}\n\nเราได้แจ้งยอดค้าง {amt} ของรายการ {ref} ไปก่อนหน้านี้แล้วแต่ยังไม่ได้รับชำระ "
                f"กรุณาชำระหรือยืนยันวันชำระภายในวันที่ {deadline:%d/%m/%Y}\n\n"
                f"Dear {who},\n\nWe previously notified you of {amt} outstanding on {ref}, which remains unpaid. "
                f"Please settle or confirm a payment date by {deadline:%d %b %Y}.\n\n— Zentry Finance Ops")
    else:
        subject = f"ส่งเรื่องให้ผู้จัดการพิจารณา / Escalation notice — {ref}"
        body = (f"เรียน {who}\n\nยอด {amt} ของรายการ {ref} ยังค้างชำระหลังการแจ้งเตือนสองครั้ง "
                "เรื่องนี้ถูกส่งต่อให้ผู้จัดการฝ่ายการเงินดำเนินการต่อ\n\n"
                f"Dear {who},\n\n{amt} on {ref} remains outstanding after two reminders. The matter has been "
                "escalated to our finance manager.\n\n— Zentry Finance Ops")
    return subject, body


def compose(fu: dict, level: int, today: date) -> tuple[str, str, dict]:
    """(subject, body, audit) — the LLM version if configured and grounded, else the template."""
    subject, body = draft(fu, level, today)
    audit = {"mode": "llm" if llm.configured() else "offline", "model": llm.model_name(), "level": level}
    if not llm.configured():
        return subject, body, audit
    facts = {"kind": fu["kind"], "counterparty": fu["counterparty"], "amount": format_thb(fu["amount_due_satang"]),
             "reference": (fu.get("source_ref") or "").split(":", 1)[-1], "level": level,
             "promise_date": str(fu.get("promise_date") or ""), "today": today.isoformat(), "template": body}
    prompt = json.dumps(facts, ensure_ascii=False)
    out = llm.chat_json(SYSTEM, prompt) or {}
    text = out.get("body")
    allowed = {facts["reference"]}
    if isinstance(text, str) and text.strip() and facts["amount"] in text and llm.grounded(text, allowed):
        subject, body = str(out.get("subject") or subject), text.strip()
    audit |= {"system_prompt": SYSTEM, "prompt": prompt, "output": json.dumps(out, ensure_ascii=False)[:8000]}
    return subject, body, audit


# --------------------------------------------------------------------------- reading replies
TH_DAYS = {"จันทร์": 0, "อังคาร": 1, "พุธ": 2, "พฤหัส": 3, "ศุกร์": 4, "เสาร์": 5, "อาทิตย์": 6}
EN_DAYS = {d: i for i, d in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))}
REPLY_SYSTEM = """Extract the payment promise from a counterparty's reply. Today is {today}.
Return JSON: {{"promise_date": "YYYY-MM-DD" or null, "paid": bool, "summary": str (one short English sentence)}}"""


def read_reply(text: str, today: date) -> dict:
    """Promise date from replies like "จะโอนวันศุกร์", "will pay on 14/11", "โอนแล้วค่ะ"."""
    if llm.configured():
        out = llm.chat_json(REPLY_SYSTEM.format(today=today.isoformat()), text, temperature=0)
        if out and (out.get("promise_date") is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(out["promise_date"]))):
            return {"promise_date": out.get("promise_date"), "paid": bool(out.get("paid")),
                    "summary": str(out.get("summary") or ""), "mode": "llm"}
    low = text.casefold()
    paid = bool(re.search(r"โอนแล้ว|ชำระแล้ว|จ่ายแล้ว|already paid|have paid|paid today|transferred", low))
    promise: date | None = None
    if m := re.search(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", text):
        d, mo, y = int(m[1]), int(m[2]), m[3]
        year = today.year if not y else (int(y) - 543 if int(y) > 2400 else int(y) + (2000 if int(y) < 100 else 0))
        try:
            promise = date(year, mo, d)
            if promise < today and not y:
                promise = date(year + 1, mo, d)
        except ValueError:
            promise = None
    elif "พรุ่งนี้" in text or "tomorrow" in low:
        promise = today + timedelta(days=1)
    elif "วันนี้" in text or "today" in low:
        promise = today
    else:
        for names in (TH_DAYS, EN_DAYS):
            for name, wd in names.items():
                if name in low:
                    promise = today + timedelta(days=(wd - today.weekday()) % 7 or 7)
                    break
            if promise:
                break
    summary = ("Counterparty says it has paid." if paid else
               f"Counterparty promises to pay on {promise.isoformat()}." if promise else "No payment date given.")
    return {"promise_date": promise.isoformat() if promise else None, "paid": paid, "summary": summary,
            "mode": "offline"}
