"""Write the dataset to Postgres (COPY) and raw settlement CSVs to disk."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import psycopg

from .generate import END, START, Dataset

# Everything the seed owns. Truncated together so `make seed` is repeatable.
TABLES = [
    "audit_log", "messages", "follow_ups", "recon_matches", "recon_runs", "case_links", "cases",
    "alerts", "train_runs", "model_versions", "scenarios", "outbox", "settlements", "transactions",
    "accounts", "customers",
]

COLUMNS = {
    "customers": ["id", "name_th", "name_en", "kyc_level", "risk_score", "created_at"],
    "accounts": ["id", "customer_id", "type", "bank_code", "opened_at", "status", "gt_role", "gt_ring", "gt_layer"],
    "transactions": ["id", "from_account", "to_account", "amount_satang", "channel", "ref_no", "ts", "device_id",
                     "gt_is_fraud", "gt_ring"],
    "settlements": ["id", "source", "ref_no", "counterparty_name", "amount_satang", "fee_satang", "value_date",
                    "raw_file_key", "gt_break_type"],
}


def load_db(ds: Dataset, database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("truncate " + ", ".join(f"public.{t}" for t in TABLES) + " restart identity cascade")
        for table, cols in COLUMNS.items():
            rows = getattr(ds, table)
            with cur.copy(f"copy public.{table} ({', '.join(cols)}) from stdin") as copy:
                for row in rows:
                    copy.write_row(row)
            print(f"  {table:<13} {len(rows):>8,}")


def write_files(ds: Dataset, out_dir: Path) -> dict:
    """Raw settlement CSVs (as a gateway/bank would send them) + a ground-truth manifest."""
    raw = out_dir / "raw"
    by_file: dict[str, list] = defaultdict(list)
    for r in ds.settlements:
        by_file[r[7]].append(r)
    for key, rows in by_file.items():
        path = raw / key
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ref_no", "counterparty_name", "amount_thb", "fee_thb", "value_date"])
            for r in rows:
                w.writerow([r[2], r[3], f"{r[4] / 100:.2f}", f"{r[5] / 100:.2f}", r[6]])

    manifest = {
        "period": {"start": START.isoformat(), "end": END.isoformat()},
        "counts": {
            "customers": len(ds.customers),
            "accounts": len(ds.accounts),
            "transactions": len(ds.transactions),
            "fraud_transactions": sum(1 for t in ds.transactions if t[8]),
            "mule_accounts": sum(1 for a in ds.accounts if a[6] == "mule"),
            "victim_accounts": sum(1 for a in ds.accounts if a[6] == "victim"),
            "rings": len(ds.rings),
            "settlements": len(ds.settlements),
            "settlement_files": len(by_file),
            "breaks": len(ds.breaks),
        },
        "rings": [
            {"ring": r["ring"], "size": sum(len(v) for v in r["layers"].values()),
             "layer_sizes": {k: len(v) for k, v in r["layers"].items()}, "victims": len(r["victims"]),
             "activity_start": r["activity_start"]}
            for r in ds.rings
        ],
        "breaks": ds.breaks,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest
