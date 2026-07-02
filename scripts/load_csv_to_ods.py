#!/usr/bin/env python3
"""
HoneyBadge CSV -> ODS PostgreSQL Loader

Bulk-loads PTP CSV files into ODS PostgreSQL tables using asyncpg's
COPY protocol (10x faster than executemany).

Tables are loaded in dependency order:
    organization -> supplier -> item ->
    po -> po_line -> receipt -> receipt_line ->
    invoice -> invoice_line

Before loading, each target table is TRUNCATEd (CASCADE) for re-entrancy:
re-running with the same batch_id produces a clean state.

Usage:
    python scripts/load_csv_to_ods.py \\
        --csv-dir deploy/test-data/ptp_csv/ \\
        --batch-id ETL-TEST-001 \\
        --postgres-dsn "postgresql://honeybadge:honeybadge123@localhost:5432/honeybadge_ods"
"""

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

import asyncpg

# Load order respects FK dependencies (parent before child).
LOAD_ORDER = [
    "ods_organization",
    "ods_supplier",
    "ods_item",
    "ods_purchase_order",
    "ods_purchase_order_line",
    "ods_receipt",
    "ods_receipt_line",
    "ods_ap_invoice",
    "ods_ap_invoice_line",
]


async def truncate_table(conn: asyncpg.Connection, table: str) -> None:
    """Truncate a table (CASCADE) for re-entrancy."""
    await conn.execute(f'TRUNCATE TABLE "{table}" CASCADE;')
    print(f"  TRUNCATE {table}")


async def load_csv_to_table(
    pool: asyncpg.Pool,
    table: str,
    csv_path: Path,
) -> int:
    """Load a single CSV file into its ODS table via COPY.

    Returns the number of rows inserted.
    """
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = [tuple(row) for row in reader]

    if not rows:
        print(f"  {table}: 0 rows (empty CSV)")
        return 0

    # asyncpg copy_records_to_table expects column names without quotes
    # and records as a list of tuples.
    async with pool.acquire() as conn:
        await conn.copy_records_to_table(
            table_name=table,
            records=rows,
            columns=header,
        )
    print(f"  {table}: {len(rows)} rows loaded")
    return len(rows)


async def verify_row_counts(pool: asyncpg.Pool, batch_id: str) -> dict[str, int]:
    """Verify row counts per table for the given batch_id."""
    counts = {}
    async with pool.acquire() as conn:
        for table in LOAD_ORDER:
            count = await conn.fetchval(
                f'SELECT COUNT(*) FROM "{table}" WHERE etl_batch_id = $1',
                batch_id,
            )
            counts[table] = count
    return counts


async def load_all(
    csv_dir: Path,
    batch_id: str,
    dsn: str,
) -> int:
    """Load all 9 PTP CSV files into ODS PostgreSQL."""
    print(f"Loading CSV -> ODS (batch={batch_id})")
    print(f"  DSN: {dsn}")
    print(f"  CSV dir: {csv_dir}")

    missing = [t for t in LOAD_ORDER if not (csv_dir / f"{t}.csv").exists()]
    if missing:
        print(f"ERROR: Missing CSV files: {missing}", file=sys.stderr)
        return 1

    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4)
    try:
        # Truncate all tables (children first to respect CASCADE, though
        # CASCADE handles ordering anyway).
        async with pool.acquire() as conn:
            for table in reversed(LOAD_ORDER):
                await truncate_table(conn, table)

        # Load each CSV
        total = 0
        for table in LOAD_ORDER:
            csv_path = csv_dir / f"{table}.csv"
            loaded = await load_csv_to_table(pool, table, csv_path)
            total += loaded

        # Verify
        print(f"\nVerifying row counts (batch_id={batch_id}):")
        counts = await verify_row_counts(pool, batch_id)
        for table, count in counts.items():
            print(f"  {table:30s} {count:>6d}")
        print(f"  {'TOTAL':30s} {sum(counts.values()):>6d}")

        print(f"\nDone. {total} rows loaded across {len(LOAD_ORDER)} tables.")
        return 0
    finally:
        await pool.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load PTP CSV files into ODS PostgreSQL",
    )
    parser.add_argument(
        "--csv-dir",
        type=str,
        default="deploy/test-data/ptp_csv/",
        help="Directory containing the 9 PTP CSV files",
    )
    parser.add_argument(
        "--batch-id",
        type=str,
        required=True,
        help="ETL batch identifier (must match CSV etl_batch_id column)",
    )
    parser.add_argument(
        "--postgres-dsn",
        type=str,
        default=os.environ.get(
            "POSTGRES_DSN",
            "postgresql://honeybadge:honeybadge123@localhost:5432/honeybadge_ods",
        ),
        help="PostgreSQL ODS DSN",
    )
    args = parser.parse_args()

    return asyncio.run(
        load_all(
            csv_dir=Path(args.csv_dir),
            batch_id=args.batch_id,
            dsn=args.postgres_dsn,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
