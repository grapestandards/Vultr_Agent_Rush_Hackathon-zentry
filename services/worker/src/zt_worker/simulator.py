"""Replays sim_feed into the ledger through the outbox, like a payment switch would.

    python -m zt_worker.simulator --rate 20            # demo speed, 20 tx/s
    python -m zt_worker.simulator --rate 0 --until 2026-11-05   # as fast as possible up to a time
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime

import psycopg

from zt_core.ingest import TXN_COLUMNS, ingest_transactions
from zt_core.settings import env

GT_COLUMNS = ["gt_is_fraud", "gt_ring"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rate", type=float, default=20, help="transactions per second; 0 = unthrottled")
    ap.add_argument("--until", type=datetime.fromisoformat, help="stop before this business time")
    ap.add_argument("--limit", type=int, help="stop after N transactions")
    ap.add_argument("--batch", type=int, default=1000)
    args = ap.parse_args()

    cols = TXN_COLUMNS + GT_COLUMNS
    sent, t0 = 0, time.time()
    with psycopg.connect(env("DATABASE_URL")) as conn:
        while args.limit is None or sent < args.limit:
            size = args.batch if args.rate == 0 else max(1, int(args.rate))  # ~1 s worth per batch
            if args.limit:
                size = min(size, args.limit - sent)
            where, params = ("where ts < %s", [args.until]) if args.until else ("", [])
            rows = conn.execute(f"select {', '.join(cols)} from public.sim_feed {where} order by ts, id limit %s",
                                [*params, size]).fetchall()
            if not rows:
                break
            batch = [dict(zip(cols, r)) for r in rows]
            started = time.time()
            with conn.transaction():
                ingest_transactions(conn, batch, extra_columns=GT_COLUMNS)
                conn.execute("delete from public.sim_feed where id = any(%s)", ([r["id"] for r in batch],))
            sent += len(batch)
            if args.rate:
                time.sleep(max(0.0, len(batch) / args.rate - (time.time() - started)))
            if sent % 10_000 < len(batch) or args.rate:
                print(f"\r{sent:,} sent · business time {batch[-1]['ts']:%Y-%m-%d %H:%M} · "
                      f"{sent / (time.time() - t0):,.0f} tx/s", end="", flush=True)
    print(f"\ndone: {sent:,} transactions")


if __name__ == "__main__":
    main()
