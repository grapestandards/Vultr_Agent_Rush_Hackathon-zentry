"""Build a deterministic synthetic dataset in memory.

Normal e-wallet traffic (P2P transfers inside social circles, merchant QR/PromptPay payments),
legitimate look-alikes (group collectors, new online sellers, shared devices), plus embedded mule rings: victims → layer 1 (collect) → layer 2 (split) → layer 3 (cash-out via
gold/mobile shops), each hop within minutes. Settlement files are derived from merchant payments
with reconciliation breaks injected on purpose.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .names import BANK_CODES, FIRST, LAST, MERCHANT

BKK = timezone(timedelta(hours=7))
END = datetime(2026, 11, 7, tzinfo=BKK)  # exclusive; data covers the 30 days before this
DAYS = 30
START = END - timedelta(days=DAYS)

# Hour-of-day weights for normal traffic (Bangkok time).
HOUR_WEIGHTS = [1, 0.5, 0.3, 0.2, 0.2, 0.5, 2, 4, 6, 6, 5, 6, 9, 7, 5, 5, 6, 8, 10, 10, 9, 7, 4, 2]

GATEWAY_FEE_BPS = 80  # 0.80 % MDR on QR settlements
CASHOUT_MERCHANTS = 3


@dataclass
class Dataset:
    customers: list[tuple] = field(default_factory=list)
    accounts: list[tuple] = field(default_factory=list)
    transactions: list[tuple] = field(default_factory=list)
    settlements: list[tuple] = field(default_factory=list)
    breaks: list[dict] = field(default_factory=list)  # ground-truth manifest of injected breaks
    watchlist: list[tuple] = field(default_factory=list)
    rings: list[dict] = field(default_factory=list)


def _lognormal_satang(rng: random.Random, median_baht: float, sigma: float, lo: int, hi: int) -> int:
    baht = median_baht * math.exp(rng.gauss(0, sigma))
    return int(min(max(baht, lo), hi) * 100)


_HOUR_CUM = [sum(HOUR_WEIGHTS[: i + 1]) for i in range(24)]


def _ts_on_day(rng: random.Random, day: date) -> datetime:
    hour = rng.choices(range(24), cum_weights=_HOUR_CUM)[0]
    return datetime(day.year, day.month, day.day, hour, tzinfo=BKK) + timedelta(seconds=rng.randrange(3600))


def generate(seed: int = 42, n_customers: int = 10_000, n_txns: int = 200_000, n_rings: int = 5) -> Dataset:
    rng = random.Random(seed)
    ds = Dataset()

    # ------------------------------------------------------------ customers / accounts
    n_merchants = n_customers * 3 // 100
    wallet_of: dict[str, str] = {}     # customer -> wallet account
    device_of: dict[str, str] = {}
    merchants: list[str] = []
    personal: list[str] = []           # accounts that can send P2P
    acct_owner: dict[str, str] = {}
    acct_opened: dict[str, datetime] = {}
    cust_name: dict[str, str] = {}
    acct_seq = 0

    def new_account(cust: str, kind: str, opened: datetime) -> str:
        nonlocal acct_seq
        acct_seq += 1
        aid = f"A{acct_seq:07d}"
        bank = rng.choice(BANK_CODES) if kind == "bank" else None
        ds.accounts.append([aid, cust, kind, bank, opened, "active", None, None, None])
        acct_owner[aid] = cust
        acct_opened[aid] = opened
        return aid

    for i in range(1, n_customers + 1):
        cid = f"C{i:06d}"
        created = START - timedelta(days=rng.randint(30, 1500), seconds=rng.randrange(86400))
        is_merchant = i <= n_merchants
        if is_merchant:
            (mth, men), (lth, len_) = rng.choice(MERCHANT), rng.choice(LAST)
            name_th, name_en = f"{mth} {lth}", f"{men} {len_}"
        else:
            (fth, fen), (lth, len_) = rng.choice(FIRST), rng.choice(LAST)
            name_th, name_en = f"{fth} {lth}", f"{fen} {len_}"
        kyc = rng.choices([1, 2, 3], [2, 5, 3])[0]
        ds.customers.append([cid, name_th, name_en, kyc, 0, created])
        cust_name[cid] = name_en
        device_of[cid] = f"D{rng.getrandbits(40):010x}"
        if is_merchant:
            merchants.append(new_account(cid, "merchant", created))
        else:
            wallet_of[cid] = new_account(cid, "wallet", created)
            personal.append(wallet_of[cid])
            if rng.random() < 0.3:
                personal.append(new_account(cid, "bank", created + timedelta(days=rng.randint(0, 20))))

    cashout = merchants[:CASHOUT_MERCHANTS]  # gold / mobile shops the rings cash out through
    for m in cashout:
        cust = acct_owner[m]
        ds.customers[int(cust[1:]) - 1][1:3] = ["ร้านทอง เยาวราช", "Yaowarat Gold Shop"] if m == cashout[0] \
            else ["ร้านมือถือ ประตูน้ำ", "Pratunam Mobile Shop"]
        cust_name[cust] = ds.customers[int(cust[1:]) - 1][2]  # settlement files use the trading name

    account_row = {row[0]: row for row in ds.accounts}
    txns: list[list] = []

    def add_txn(src: str, dst: str, amount: int, channel: str, ts: datetime, device: str | None,
                fraud: bool = False, ring: int | None = None) -> None:
        txns.append([None, src, dst, amount, channel, None, ts, device, fraud, ring])

    # ------------------------------------------------------------ mule rings
    pool = [a for a in personal if account_row[a][2] == "wallet"]
    rng.shuffle(pool)
    mule_customers: set[str] = set()
    victims_used: set[str] = set()
    # Ring styles: fresh accounts opened for the scam, rented accounts (old, normal KYC, own phones,
    # everyday activity), and slow layering (hours between hops instead of minutes).
    styles = {1: ("fresh", 1), 2: ("rented", 1), 3: ("fresh", 1), 4: ("rented", 20), 5: ("fresh", 12)}
    rented_customers: set[str] = set()
    for r in range(1, n_rings + 1):
        style, pace = styles.get(r, ("fresh", 1))
        size = rng.randint(10, 20)
        n_l1 = round(size * 0.4)
        n_l3 = max(2, round(size * 0.25))
        n_l2 = size - n_l1 - n_l3
        activity_start = START + timedelta(days=rng.randint(4, DAYS - 6))
        ring_devices = [f"D{rng.getrandbits(40):010x}" for _ in range(2)]  # devices shared inside a ring
        layers: dict[int, list[str]] = {1: [], 2: [], 3: []}
        for layer, n in ((1, n_l1), (2, n_l2), (3, n_l3)):
            for _ in range(n):
                acct = pool.pop()
                cust = acct_owner[acct]
                mule_customers.add(cust)
                row = account_row[acct]
                row[6], row[7], row[8] = "mule", r, layer
                if style == "rented":
                    rented_customers.add(cust)       # keeps its age, KYC and phone
                else:
                    opened = activity_start - timedelta(days=rng.randint(2, 25), seconds=rng.randrange(86400))
                    row[4] = opened
                    acct_opened[acct] = opened
                    ds.customers[int(cust[1:]) - 1][3] = 1          # thin KYC
                    ds.customers[int(cust[1:]) - 1][5] = opened
                    device_of[cust] = rng.choice(ring_devices)
                layers[layer].append(acct)

        victims = []
        n_victims = rng.randint(8, 16)
        while len(victims) < n_victims:
            v = rng.choice(pool)
            if v not in victims_used:
                victims_used.add(v)
                victims.append(v)
                account_row[v][6], account_row[v][7] = "victim", r

        # Each victim is scammed in one episode spread across the ring's active days.
        for v in victims:
            t = activity_start + timedelta(days=rng.randint(0, 4), hours=rng.randint(9, 20),
                                           minutes=rng.randrange(60))
            for _ in range(rng.randint(1, 3)):
                amount = _lognormal_satang(rng, 60_000, 0.7, 5_000, 450_000)
                l1 = rng.choice(layers[1])
                add_txn(v, l1, amount, rng.choice(["promptpay", "transfer"]), t,
                        device_of[acct_owner[v]], True, r)
                _layer_out(rng, add_txn, l1, amount, t, layers, device_of, acct_owner, cashout, r, depth=1, pace=pace)
                t += timedelta(minutes=rng.randint(10, 90))

        ds.rings.append({"ring": r, "style": style, "pace": pace, "layers": {k: v for k, v in layers.items()},
                         "victims": victims, "activity_start": activity_start.isoformat()})

    # ------------------------------------------------------------ legitimate look-alikes
    # Real users whose flows resemble mules, so the detector has to earn its precision.
    legit = [a for a in pool if a not in victims_used]
    everyday = [a for a in personal if acct_owner[a] not in mule_customers]  # their friends / buyers
    days_all = [(START + timedelta(days=d)).date() for d in range(DAYS)]
    venues = merchants[CASHOUT_MERCHANTS:]

    # 1. Group collectors: friends chip in for a trip / party / condo fee, the organiser pays it
    #    all out minutes later (fan-in + pass-through, but one payee and no layering).
    for acct in legit[:60]:
        cust = acct_owner[acct]
        for _ in range(rng.randint(1, 3)):
            t = _ts_on_day(rng, rng.choice(days_all))
            total = 0
            for friend in rng.sample(everyday, rng.randint(5, 14)):
                if friend == acct:
                    continue
                share = _lognormal_satang(rng, 900, 0.5, 100, 6000)
                t += timedelta(minutes=rng.randint(1, 15))
                add_txn(friend, acct, share, "promptpay", t, device_of[acct_owner[friend]])
                total += share
            payee = rng.choice(venues) if rng.random() < 0.6 else rng.choice(everyday)
            out = int(total * rng.uniform(0.92, 1.0))
            for part in _split(rng, out, rng.randint(1, 2)):
                t += timedelta(minutes=rng.randint(3, 40))
                add_txn(acct, payee, part, "qr" if payee in venues else "transfer", t, device_of[cust])

    # 2. New online sellers: a fresh wallet paid by many strangers, swept to the owner's own bank
    #    account every evening (new account + strangers + high out/in, but no layering).
    for acct in legit[60:100]:
        cust = acct_owner[acct]
        opened = START + timedelta(days=rng.randint(0, 18), seconds=rng.randrange(86400))
        account_row[acct][4] = acct_opened[acct] = opened
        if rng.random() < 0.5:
            ds.customers[int(cust[1:]) - 1][3] = 1
        bank = new_account(cust, "bank", opened)
        account_row[bank] = ds.accounts[-1]
        day = opened.date() + timedelta(days=1)
        while day < END.date():
            if rng.random() < 0.6:
                takings = 0
                for buyer in rng.sample(everyday, rng.randint(3, 12)):
                    amount = _lognormal_satang(rng, 450, 0.8, 50, 9000)
                    add_txn(buyer, acct, amount, "promptpay", _ts_on_day(rng, day), device_of[acct_owner[buyer]])
                    takings += amount
                sweep = datetime(day.year, day.month, day.day, 21, tzinfo=BKK) + timedelta(minutes=rng.randrange(120))
                add_txn(acct, bank, int(takings * rng.uniform(0.9, 1.0)), "transfer", sweep, device_of[cust])
            day += timedelta(days=1)

    # 3. Shared devices: families on one phone, and phone-shop agents who set up many wallets.
    family_heads = legit[100:160]
    rest = legit[160:]
    for head in family_heads:
        for member in rest[:rng.randint(1, 4)]:
            device_of[acct_owner[member]] = device_of[acct_owner[head]]
        rest = rest[4:]
    for _ in range(8):
        agent_device = f"D{rng.getrandbits(40):010x}"
        for member in rest[:rng.randint(6, 12)]:
            device_of[acct_owner[member]] = agent_device
        rest = rest[12:]

    # ------------------------------------------------------------ normal traffic
    normal_senders = [a for a in personal if acct_owner[a] not in mule_customers]
    activity = {a: rng.lognormvariate(0, 1.0) for a in normal_senders}
    sender_weights = [activity[a] for a in normal_senders]
    contacts = {a: rng.sample(normal_senders, 8) for a in normal_senders}
    shop_weights = [1 / (i + 1) ** 0.8 for i in range(len(merchants))]
    days = [(START + timedelta(days=d)).date() for d in range(DAYS)]

    # Mules keep a little ordinary-looking activity so they are not trivially separable.
    for cust in sorted(mule_customers):
        acct = wallet_of[cust]
        for _ in range(rng.randint(15, 40) if cust in rented_customers else rng.randint(2, 6)):
            day = rng.choice(days)
            ts = _ts_on_day(rng, day)
            if ts > acct_opened[acct]:
                add_txn(acct, rng.choices(merchants, shop_weights)[0], _lognormal_satang(rng, 150, 0.6, 20, 3000),
                        "qr", ts, device_of[cust])

    remaining = n_txns - len(txns)
    # Draw all weighted picks up front: rng.choices re-sums the weights on every call otherwise.
    senders = rng.choices(normal_senders, sender_weights, k=remaining)
    shops = iter(rng.choices(merchants, shop_weights, k=remaining))
    for src in senders:
        ts = _ts_on_day(rng, rng.choice(days))
        dev = device_of[acct_owner[src]]
        roll = rng.random()
        if roll < 0.55:
            dst = rng.choice(contacts[src]) if rng.random() < 0.9 else rng.choice(normal_senders)
            if dst == src:
                continue
            add_txn(src, dst, _lognormal_satang(rng, 500, 1.0, 1, 50_000),
                    rng.choice(["promptpay", "promptpay", "transfer"]), ts, dev)
        else:
            dst = next(shops)
            channel = "qr" if roll < 0.9 else "promptpay"
            add_txn(src, dst, _lognormal_satang(rng, 250, 0.9, 10, 20_000), channel, ts, dev)

    txns = [t for t in txns if START <= t[6] < END and t[6] >= acct_opened[t[1]] and t[6] >= acct_opened[t[2]]]
    txns.sort(key=lambda t: t[6])
    prefixes = {"promptpay": "PP", "transfer": "TR", "qr": "QR"}
    for i, t in enumerate(txns, 1):
        t[0] = f"TX{i:08d}"
        t[5] = f"{prefixes[t[4]]}{t[6]:%y%m%d}{i:08d}"
    ds.transactions = txns

    _settlements(rng, ds, txns, account_row, cust_name, set(merchants))
    _watchlist(rng, ds)
    return ds


def _watchlist(rng: random.Random, ds: Dataset) -> None:
    """Synthetic internal blacklist: two cash-out mules from ring 2 (so screening has true hits)
    plus unrelated decoy names."""
    names = {c[0]: (c[2], c[1]) for c in ds.customers}
    ring2_l3 = sorted(a[1] for a in ds.accounts if a[7] == 2 and a[8] == 3)[:2]
    for cust in ring2_l3:
        en, th = names[cust]
        ds.watchlist.append((en, th, "internal_mule_blacklist", "Previously reported as a mule (synthetic)"))
    for _ in range(12):
        (fth, fen), (lth, len_) = rng.choice(FIRST), rng.choice(LAST)
        ds.watchlist.append((f"{fen} {len_}", f"{fth} {lth}", "synthetic_sanctions", "Decoy entry for demo"))


def _layer_out(rng, add_txn, src, amount, t, layers, device_of, acct_owner, cashout, ring, depth, pace=1) -> None:
    """Forward most of the money one layer down within minutes × pace (layer 3 cashes out partially)."""
    if depth == 3:
        out = int(amount * rng.uniform(0.4, 0.7))
        for part in _split(rng, out, rng.randint(1, 3)):
            t += timedelta(minutes=rng.randint(10, 120) * pace)
            add_txn(src, rng.choice(cashout), part, "qr", t, device_of[acct_owner[src]], True, ring)
        return
    out = int(amount * rng.uniform(0.90, 0.98))
    for part in _split(rng, out, rng.randint(1, 3)):
        dst = rng.choice(layers[depth + 1])
        t2 = t + timedelta(minutes=rng.randint(2, 15 if depth == 1 else 20) * pace, seconds=rng.randrange(60))
        add_txn(src, dst, part, rng.choice(["promptpay", "transfer"]), t2, device_of[acct_owner[src]], True, ring)
        _layer_out(rng, add_txn, dst, part, t2, layers, device_of, acct_owner, cashout, ring, depth + 1, pace)


def _split(rng: random.Random, total: int, n: int) -> list[int]:
    if n == 1 or total < n * 100:
        return [total]
    cuts = sorted(rng.sample(range(1, total), n - 1))
    return [b - a for a, b in zip([0, *cuts], [*cuts, total])]


def _settlements(rng, ds: Dataset, txns, account_row, cust_name, merchant_set) -> None:
    """Gateway file: one net row per merchant per day for QR (many-to-one, T+1, MDR fee).
    Bank statement: one row per PromptPay payment to a merchant (exact ref). Then inject breaks."""
    seq = 0

    def sid() -> str:
        nonlocal seq
        seq += 1
        return f"ST{seq:07d}"

    owner_name = {a: cust_name[row[1]] for a, row in account_row.items()}
    qr_batches: dict[tuple[str, date], int] = defaultdict(int)
    bank_rows: list[list] = []
    for t in txns:
        _, src, dst, amount, channel, ref, ts, *_ = t
        if dst not in merchant_set:
            continue
        if channel == "qr":
            qr_batches[(dst, ts.date())] += amount
        elif channel == "promptpay":
            value_date = ts.date() + timedelta(days=1 if ts.hour >= 22 else 0)
            bank_rows.append([sid(), "bank", ref, owner_name[src], amount, 0, value_date,
                              f"settlements/bank/{value_date}.csv", None])

    gateway_rows = []
    for (merchant, day), gross in sorted(qr_batches.items()):
        fee = gross * GATEWAY_FEE_BPS // 10_000
        value_date = day + timedelta(days=1)
        gateway_rows.append([sid(), "gateway", f"GW{day:%y%m%d}{merchant}", owner_name[merchant],
                             gross - fee, fee, value_date, f"settlements/gateway/{value_date}.csv", None])

    per_type = 10
    end_day = (END - timedelta(days=1)).date()
    # timing: late-evening payments on the last day settle after the period closes
    late = [r for r in bank_rows if r[6] == end_day and r[8] is None][:per_type]
    for r in late:
        r[6] = end_day + timedelta(days=rng.randint(3, 4))
        r[7] = f"settlements/bank/{r[6]}.csv"
        r[8] = "timing"
        ds.breaks.append({"type": "timing", "settlement_id": r[0], "ref_no": r[2]})
    # Each remaining break type gets its own untouched rows.
    clean = [i for i, r in enumerate(bank_rows) if r[8] is None]
    take = iter(rng.sample(clean, per_type * 3))
    for _ in range(per_type):  # amount_mismatch
        r = bank_rows[next(take)]
        r[4] += rng.choice([-1, 1]) * rng.randint(100, 50_000)
        r[8] = "amount_mismatch"
        ds.breaks.append({"type": "amount_mismatch", "settlement_id": r[0], "ref_no": r[2]})
    dupes = []
    for _ in range(per_type):  # duplicate
        r = bank_rows[next(take)]
        d = [sid(), *r[1:8], "duplicate"]
        dupes.append(d)
        ds.breaks.append({"type": "duplicate", "settlement_id": d[0], "ref_no": r[2]})
    missing = set()
    for _ in range(per_type):  # missing_in_bank: ledger has it, bank never paid
        idx = next(take)
        missing.add(idx)
        ds.breaks.append({"type": "missing_in_bank", "ref_no": bank_rows[idx][2]})
    for _ in range(per_type):  # missing_in_ledger: bank credit with no ledger transaction
        day = (START + timedelta(days=rng.randrange(DAYS))).date()
        ref = f"PP{day:%y%m%d}9{rng.randrange(10**7):07d}"
        r = [sid(), "bank", ref, rng.choice(list(owner_name.values())), rng.randint(10_000, 500_000), 0,
             day, f"settlements/bank/{day}.csv", "missing_in_ledger"]
        dupes.append(r)
        ds.breaks.append({"type": "missing_in_ledger", "settlement_id": r[0], "ref_no": ref})
    for r in rng.sample(gateway_rows, per_type):  # fee: gateway charged more than the contracted MDR
        extra = max(100, r[5])
        r[5] += extra
        r[4] -= extra
        r[8] = "fee"
        ds.breaks.append({"type": "fee", "settlement_id": r[0], "ref_no": r[2]})

    bank_rows = [r for i, r in enumerate(bank_rows) if i not in missing] + dupes
    ds.settlements = gateway_rows + bank_rows
