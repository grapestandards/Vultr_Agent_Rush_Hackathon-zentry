"""Recon agent (W2 step 3): explain each break and draft the adjusting journal entry.

Journal entries are built deterministically from the matched amounts (accounting must be exact);
the LLM, when configured, only rewrites the explanation and may cite only ids from that break's facts.
Finance Ops confirms or dismisses every entry; nothing posts on its own.
"""

from __future__ import annotations

import json

from zt_core.money import format_thb
from zt_core.recon import Match

from . import llm

BANK = "1010 Bank – settlement account"
PP_CLEARING = "1120 Settlement clearing – PromptPay"
GW_CLEARING = "1130 Gateway clearing – QR"
IN_TRANSIT = "1140 Settlement in transit"
FEE_REFUND = "1210 Receivable – gateway fee refund"
BANK_CLAIM = "1220 Receivable – settlement claims"
SUSPENSE = "2190 Suspense – unidentified receipts"
DUPLICATES = "2195 Duplicate credits to return"

GATEWAY = ("QR payment gateway (synthetic)", "settlements@gateway.example")
BANK_DESK = ("Partner bank – PromptPay settlement desk (synthetic)", "settlement-desk@bank.example")

SYSTEM = """You are Zentry's reconciliation assistant for a Thai e-wallet. All data is synthetic.
For each break you get its type and facts. Write a 1–2 sentence plain explanation for Finance Ops:
what most likely happened and what to check. Cite only references and ids present in that break's facts.
Return JSON: {"explanations": {"<key>": "<text>", ...}}"""


def _entry(memo: str, debit: str, credit: str, amount: int) -> dict:
    return {"memo": memo, "lines": [{"account": debit, "debit_satang": amount, "credit_satang": 0},
                                    {"account": credit, "debit_satang": 0, "credit_satang": amount}]}


def draft(m: Match) -> tuple[str, dict | None, dict | None]:
    """(explanation, journal entry, suggested follow-up) for one break."""
    f, d = m.facts, m.diff_satang or 0
    ref = f.get("ref_no", "")
    if m.break_type == "timing":
        amt = f["ledger_satang"]
        return (f"{ref} ({format_thb(amt)}) was paid on {f['payment_date']} but the bank credited it on "
                f"{f['value_date']}, {f['lag_days']} days later — after the period cut-off. Amounts agree; "
                "carry it as in transit and it clears in the next run.",
                _entry(f"Settlement in transit for {ref}; reverse when the {f['value_date']} credit posts",
                       IN_TRANSIT, PP_CLEARING, amt), None)
    if m.break_type == "fee":
        extra = -d
        return (f"Gateway batch {ref} for {f['merchant_name']} ({f['payments']} QR payments, gross "
                f"{format_thb(f['gross_satang'])}) deducted a fee of {format_thb(f['fee_satang'])}; the contracted "
                f"{f['fee_bps'] / 100:.2f}% MDR is {format_thb(f['expected_fee_satang'])}. Claim the "
                f"{format_thb(abs(extra))} difference from the gateway.",
                _entry(f"Excess MDR on {ref} claimed from gateway", FEE_REFUND, GW_CLEARING, extra) if extra > 0
                else _entry(f"MDR under-charged on {ref}", GW_CLEARING, FEE_REFUND, -extra),
                {"counterparty": GATEWAY[0], "contact": GATEWAY[1], "amount_satang": extra,
                 "title": f"Excess MDR refund — {ref}"} if extra > 0 else None)
    if m.break_type == "amount_mismatch":
        if "gross_satang" in f:
            ledger, settled = f["gross_satang"], f["gross_satang"] + d
        else:
            ledger, settled = f["ledger_satang"], f["settled_satang"]
        who = GATEWAY if "gross_satang" in f else BANK_DESK
        if d < 0:
            return (f"{ref}: the ledger shows {format_thb(ledger)} but only {format_thb(settled)} was settled, "
                    f"{format_thb(-d)} short. Same reference and date, so it is not a timing issue — raise a "
                    "short-settlement claim.",
                    _entry(f"Short settlement on {ref}", BANK_CLAIM, PP_CLEARING if who is BANK_DESK else GW_CLEARING, -d),
                    {"counterparty": who[0], "contact": who[1], "amount_satang": -d,
                     "title": f"Short settlement — {ref}"})
        return (f"{ref}: {format_thb(settled)} was settled against a ledger amount of {format_thb(ledger)}, "
                f"{format_thb(d)} over. Hold the excess in suspense until the source is confirmed.",
                _entry(f"Over-settlement on {ref} held in suspense", PP_CLEARING, SUSPENSE, d), None)
    if m.break_type == "duplicate":
        return (f"{ref} was credited twice ({m.settlement_id} repeats {f['duplicate_of']}). The ledger has one "
                f"payment of {format_thb(f['ledger_satang'])}; the second credit is not ours to keep.",
                _entry(f"Duplicate bank credit {m.settlement_id} for {ref}", PP_CLEARING, DUPLICATES, d), None)
    if m.break_type == "missing_in_bank":
        amt = -d
        return (f"{m.transaction_id} ({ref}, {format_thb(amt)} to {f['merchant_name']} on {f['payment_date']}) "
                "is in the ledger but no settlement arrived for it. Claim it from the settlement bank.",
                _entry(f"Unsettled {f['channel']} payment {m.transaction_id}", BANK_CLAIM, PP_CLEARING, amt),
                {"counterparty": BANK_DESK[0], "contact": BANK_DESK[1], "amount_satang": amt,
                 "title": f"Settlement not received — {ref}"})
    if m.break_type == "missing_in_ledger":
        return (f"The bank credited {format_thb(d)} under {ref} from \"{f['counterparty_name']}\" on {f['value_date']}, "
                "but no ledger transaction carries that reference or amount. Park it in suspense and trace the sender.",
                _entry(f"Unidentified credit {m.settlement_id} ({ref})", PP_CLEARING, SUSPENSE, d), None)
    return ("", None, None)


def explain_all(breaks: list[Match]) -> tuple[list[tuple[str, dict | None, dict | None]], dict]:
    """Drafts for every break, plus the audit record (prompt + output) of the LLM call if one was made."""
    drafts = [draft(m) for m in breaks]
    audit = {"mode": "llm" if llm.configured() else "offline", "model": llm.model_name(), "breaks": len(breaks)}
    if not llm.configured() or not breaks:
        return drafts, audit
    facts = {str(i): {"type": m.break_type, "transaction_id": m.transaction_id, "settlement_id": m.settlement_id,
                      "diff_satang": m.diff_satang, **{k: v for k, v in m.facts.items() if k != "transaction_ids"}}
             for i, m in enumerate(breaks)}
    prompt = json.dumps(facts, ensure_ascii=False, default=str)
    out = llm.chat_json(SYSTEM, prompt) or {}
    rewritten = out.get("explanations") or {}
    used = 0
    for i, m in enumerate(breaks):
        text = rewritten.get(str(i))
        allowed = {v for v in (m.transaction_id, m.settlement_id, m.facts.get("ref_no"),
                               m.facts.get("duplicate_of"), m.facts.get("merchant")) if v}
        if isinstance(text, str) and text.strip() and llm.grounded(text, allowed):
            drafts[i] = (text.strip(), drafts[i][1], drafts[i][2])
            used += 1
    audit |= {"system_prompt": SYSTEM, "prompt": prompt[:20_000], "output": json.dumps(out, ensure_ascii=False)[:20_000],
              "llm_explanations_used": used}
    return drafts, audit
