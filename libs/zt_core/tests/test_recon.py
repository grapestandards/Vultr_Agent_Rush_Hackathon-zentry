from datetime import date

from zt_core.recon import LedgerTxn, Settlement, reconcile, summarize

D1, D2 = date(2026, 10, 8), date(2026, 10, 9)


def pp(i, amount, day=D1, payer="Somchai Jaidee"):
    return LedgerTxn(f"TX{i:08d}", f"PP{i:010d}", "A0000010", "Cafe Test", payer, amount, "promptpay", day)


def qr(i, amount, merchant="A0000020", name="Gold Test"):
    return LedgerTxn(f"TX9{i:07d}", f"QR{i}", merchant, name, "Payer", amount, "qr", D1)


def bank(i, ref, amount, vd=D1, name="Somchai Jaidee"):
    return Settlement(f"ST{i:07d}", "bank", ref, name, amount, 0, vd)


def breaks(ms):
    return sorted((m.break_type, m.transaction_id, m.settlement_id) for m in ms if m.break_type)


def test_three_passes_and_every_break_type():
    ledger = [pp(1, 10_000), pp(2, 20_000), pp(3, 30_000), pp(4, 40_000), pp(5, 50_000), pp(6, 60_000, payer="Malee Sukjai"),
              qr(1, 100_000), qr(2, 50_000), qr(3, 10_000, "A0000021", "Phone Test")]
    gross = 150_000
    settlements = [
        bank(1, "PP0000000001", 10_000),                     # clean
        bank(2, "PP0000000002", 19_000),                     # amount_mismatch
        bank(3, "PP0000000003", 30_000, date(2026, 10, 12)),  # timing
        bank(4, "PP0000000004", 40_000), bank(5, "PP0000000004", 40_000),  # duplicate
        # pp(5) never settles → missing_in_bank
        bank(6, "PPBADREF", 60_000, D2, "Malee Sukjai."),     # fuzzy pass
        bank(7, "PP9999999999", 77_700, D2, "Nobody"),       # missing_in_ledger
        Settlement("ST0000008", "gateway", "GW1", "Gold Test", gross - 1200, 1200, D2),   # clean, 0.80 %
        Settlement("ST0000009", "gateway", "GW2", "Phone Test", 10_000 - 300, 300, D2),   # fee: expected 80
    ]
    ms = reconcile(ledger, settlements, D1, D1, fee_bps=80)
    assert breaks(ms) == sorted([
        ("amount_mismatch", "TX00000002", "ST0000002"),
        ("timing", "TX00000003", "ST0000003"),
        ("duplicate", "TX00000004", "ST0000005"),
        ("missing_in_bank", "TX00000005", None),
        ("missing_in_ledger", None, "ST0000007"),
        ("fee", "TX90000003", "ST0000009"),
    ])
    rules = {m.transaction_id: m.match_rule for m in ms if not m.break_type}
    assert rules["TX00000001"] == "ref_exact"
    assert rules["TX00000006"] == "amount_time_fuzzy"
    assert rules["TX90000001"] == rules["TX90000002"] == "many_to_one"
    fee = next(m for m in ms if m.break_type == "fee")
    assert fee.diff_satang == 80 - 300
    s = summarize(ms)
    assert s["breaks"] == 6 and s["by_break"]["duplicate"] == 1


def test_settlements_after_period_are_not_missing_in_ledger():
    ms = reconcile([], [bank(1, "PP1", 1000, date(2026, 10, 12))], D1, D1, fee_bps=80)
    assert ms == []
