"""Reconciliation matching engine (W2 step 2): ledger × gateway settlement file × bank statement.

Three passes, then classification of what is left:
1. ref_exact         bank statement row ↔ PromptPay ledger txn by reference number
2. amount_time_fuzzy same amount, value date within ±2 days, payer name similarity ≥ 0.85
3. many_to_one       one gateway row = a merchant's QR payments for a day, net of the contracted MDR

Breaks: timing (settled after the allowed lag), fee (MDR above contract), amount_mismatch,
duplicate (second bank credit for one ref), missing_in_bank (ledger paid, no settlement),
missing_in_ledger (bank credit with no ledger txn). Pure functions; the worker loads and stores.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher

MAX_LAG_DAYS = 2          # value date may trail the payment date by this much before it is a timing break
FUZZY_DAYS = 2
FUZZY_MIN_SIMILARITY = 0.85
SCOPE_AFTER_DAYS = 7      # settlements this far past period end are loaded (late settlements)


@dataclass(frozen=True)
class LedgerTxn:
    id: str
    ref_no: str
    merchant: str          # receiving merchant account
    merchant_name: str
    payer_name: str
    amount_satang: int
    channel: str           # promptpay | qr
    day: date              # Bangkok business date


@dataclass(frozen=True)
class Settlement:
    id: str
    source: str            # bank | gateway
    ref_no: str
    counterparty_name: str
    amount_satang: int
    fee_satang: int
    value_date: date


@dataclass
class Match:
    transaction_id: str | None
    settlement_id: str | None
    match_rule: str | None
    confidence: float
    break_type: str | None = None
    diff_satang: int | None = None
    facts: dict = field(default_factory=dict)  # what the explanation / journal entry is built from


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.casefold().strip(), b.casefold().strip()).ratio()


def reconcile(ledger: list[LedgerTxn], settlements: list[Settlement], start: date, end: date,
              fee_bps: int) -> list[Match]:
    out: list[Match] = []
    done_txn: set[str] = set()
    done_st: set[str] = set()
    bank = [s for s in settlements if s.source == "bank"]
    gateway = [s for s in settlements if s.source == "gateway"]

    # ---- pass 1: reference number
    by_ref: dict[str, list[Settlement]] = defaultdict(list)
    for s in sorted(bank, key=lambda s: (s.value_date, s.id)):
        by_ref[s.ref_no].append(s)
    for t in ledger:
        if t.channel != "promptpay" or not by_ref.get(t.ref_no):
            continue
        first, *extra = by_ref[t.ref_no]
        done_txn.add(t.id)
        done_st.add(first.id)
        lag = (first.value_date - t.day).days
        facts = {"ref_no": t.ref_no, "ledger_satang": t.amount_satang, "settled_satang": first.amount_satang,
                 "payment_date": t.day.isoformat(), "value_date": first.value_date.isoformat(),
                 "merchant": t.merchant, "merchant_name": t.merchant_name, "payer_name": t.payer_name}
        if first.amount_satang != t.amount_satang:
            out.append(Match(t.id, first.id, "ref_exact", 1.0, "amount_mismatch",
                             first.amount_satang - t.amount_satang, facts))
        elif lag > MAX_LAG_DAYS:
            out.append(Match(t.id, first.id, "ref_exact", 1.0, "timing", 0, facts | {"lag_days": lag}))
        else:
            out.append(Match(t.id, first.id, "ref_exact", 1.0))
        for d in extra:
            done_st.add(d.id)
            out.append(Match(t.id, d.id, "ref_exact", 1.0, "duplicate", d.amount_satang,
                             facts | {"duplicate_of": first.id, "settled_satang": d.amount_satang}))

    # ---- pass 2: amount + value date window + fuzzy payer name
    open_by_amount: dict[int, list[LedgerTxn]] = defaultdict(list)
    for t in ledger:
        if t.channel == "promptpay" and t.id not in done_txn:
            open_by_amount[t.amount_satang].append(t)
    for s in bank:
        if s.id in done_st:
            continue
        best, score = None, 0.0
        for t in open_by_amount.get(s.amount_satang, []):
            if t.id in done_txn or abs((s.value_date - t.day).days) > FUZZY_DAYS:
                continue
            sim = similarity(s.counterparty_name, t.payer_name)
            if sim >= FUZZY_MIN_SIMILARITY and sim > score:
                best, score = t, sim
        if best:
            done_txn.add(best.id)
            done_st.add(s.id)
            out.append(Match(best.id, s.id, "amount_time_fuzzy", round(score, 3)))

    # ---- pass 3: many-to-one gateway batches (merchant × day, net of MDR)
    groups: dict[tuple[str, date], list[LedgerTxn]] = defaultdict(list)
    for t in ledger:
        if t.channel == "qr":
            groups[(t.merchant, t.day)].append(t)
    gw_index: dict[tuple[str, date], list[Settlement]] = defaultdict(list)
    for s in gateway:
        gw_index[(s.counterparty_name, s.value_date)].append(s)
    for (merchant, day), txns in sorted(groups.items()):
        gross = sum(t.amount_satang for t in txns)
        name = txns[0].merchant_name
        cands = [s for s in gw_index.get((name, day + timedelta(days=1)), []) if s.id not in done_st]
        exact = [s for s in cands if s.amount_satang + s.fee_satang == gross]
        s = exact[0] if exact else (cands[0] if len(cands) == 1 else None)
        if not s:
            continue
        done_st.add(s.id)
        done_txn.update(t.id for t in txns)
        expected_fee = gross * fee_bps // 10_000
        facts = {"ref_no": s.ref_no, "merchant": merchant, "merchant_name": name, "payment_date": day.isoformat(),
                 "value_date": s.value_date.isoformat(), "gross_satang": gross, "payments": len(txns),
                 "fee_satang": s.fee_satang, "expected_fee_satang": expected_fee, "settled_satang": s.amount_satang,
                 "fee_bps": fee_bps, "transaction_ids": [t.id for t in txns][:20]}
        out.extend(Match(t.id, s.id, "many_to_one", 1.0) for t in txns)
        if not exact:
            out.append(Match(txns[0].id, s.id, "many_to_one", 0.6, "amount_mismatch",
                             s.amount_satang + s.fee_satang - gross, facts))
        elif s.fee_satang != expected_fee:
            out.append(Match(txns[0].id, s.id, "many_to_one", 1.0, "fee", expected_fee - s.fee_satang, facts))

    # ---- leftovers
    for t in ledger:
        if t.id not in done_txn and start <= t.day <= end:
            out.append(Match(t.id, None, None, 0.0, "missing_in_bank", -t.amount_satang,
                             {"ref_no": t.ref_no, "ledger_satang": t.amount_satang, "payment_date": t.day.isoformat(),
                              "merchant": t.merchant, "merchant_name": t.merchant_name, "payer_name": t.payer_name,
                              "channel": t.channel}))
    for s in settlements:
        if s.id not in done_st and start <= s.value_date <= end + timedelta(days=1):
            out.append(Match(None, s.id, None, 0.0, "missing_in_ledger", s.amount_satang,
                             {"ref_no": s.ref_no, "settled_satang": s.amount_satang, "source": s.source,
                              "value_date": s.value_date.isoformat(), "counterparty_name": s.counterparty_name}))
    return out


def summarize(matches: list[Match]) -> dict:
    rules: dict[str, int] = defaultdict(int)
    breaks: dict[str, int] = defaultdict(int)
    for m in matches:
        if m.break_type:
            breaks[m.break_type] += 1
        elif m.match_rule:
            rules[m.match_rule] += 1
    matched = sum(rules.values())
    total = matched + sum(breaks.values())
    return {"matched": matched, "breaks": sum(breaks.values()), "by_rule": dict(rules), "by_break": dict(breaks),
            "match_rate": round(matched / total, 4) if total else 0.0}
