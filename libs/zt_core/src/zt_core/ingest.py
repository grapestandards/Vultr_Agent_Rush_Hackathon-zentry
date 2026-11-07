"""Transaction ingest with the outbox pattern: the ledger row and its outbox event commit together,
so an event is never lost if NATS is down and never published for a rolled-back write."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import psycopg

from .events import txn_subject

TXN_COLUMNS = ["id", "from_account", "to_account", "amount_satang", "channel", "ref_no", "ts", "device_id"]


def txn_event(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (row[k].isoformat() if k == "ts" and not isinstance(row[k], str) else row[k]) for k in TXN_COLUMNS}


def ingest_transactions(conn: psycopg.Connection, rows: Sequence[dict[str, Any]],
                        extra_columns: Sequence[str] = ()) -> list[str]:
    """Insert transactions + outbox rows in one DB transaction. Duplicate ids are skipped (idempotent).
    Returns the ids actually inserted. `extra_columns` lets the simulator carry gt_* columns."""
    cols = TXN_COLUMNS + list(extra_columns)
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("create temp table if not exists _ingest (like public.transactions including defaults) on commit drop")
        cur.execute("truncate _ingest")
        with cur.copy(f"copy _ingest ({', '.join(cols)}) from stdin") as copy:
            for r in rows:
                copy.write_row([r[c] for c in cols])
        cur.execute(f"""
            insert into public.transactions ({', '.join(cols)})
            select distinct on (id) {', '.join(cols)} from _ingest order by id
            on conflict (id) do nothing
            returning {', '.join(TXN_COLUMNS)}""")
        inserted = [dict(zip(TXN_COLUMNS, r)) for r in cur.fetchall()]
        inserted.sort(key=lambda r: (r["ts"], r["id"]))
        if inserted:
            with cur.copy("copy public.outbox (subject, msg_id, payload) from stdin") as copy:
                for r in inserted:
                    copy.write_row([txn_subject(r["from_account"]), r["id"], json.dumps(txn_event(r))])
    return [r["id"] for r in inserted]
