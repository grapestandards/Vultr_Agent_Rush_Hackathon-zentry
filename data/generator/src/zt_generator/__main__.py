"""python -m zt_generator — seed the database with synthetic data and demo users."""

import argparse
import time
from datetime import datetime
from pathlib import Path

from zt_core.settings import env

from .generate import BKK, START, generate
from .load import load_db, write_files
from .users import ensure_demo_users


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--customers", type=int, default=10_000)
    p.add_argument("--transactions", type=int, default=200_000)
    p.add_argument("--rings", type=int, default=5)
    p.add_argument("--out", type=Path, default=Path("data/generated"))
    p.add_argument("--no-db", action="store_true", help="only write files")
    p.add_argument("--live-from", type=datetime.fromisoformat, default=START,
                   help="transactions from this time on are left in sim_feed for replay (default: all)")
    args = p.parse_args()

    t0 = time.time()
    ds = generate(args.seed, args.customers, args.transactions, args.rings)
    print(f"generated in {time.time() - t0:.1f}s")
    manifest = write_files(ds, args.out)
    print(f"wrote {manifest['counts']['settlement_files']} settlement files + manifest to {args.out}")
    if args.no_db:
        return
    live_from = args.live_from if args.live_from.tzinfo else args.live_from.replace(tzinfo=BKK)
    load_db(ds, env("DATABASE_URL"), live_from)
    users = ensure_demo_users(env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY"), env("DEMO_PASSWORD"))
    print("demo users:", ", ".join(users))
    print(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
