"""
fix_bmw_model_duplicates.py
---------------------------
Removes the redundant 'BMW ' prefix from the model column in vehicle_years
where make is already 'BMW'.

Example fix:
    make='BMW', model='BMW 3 SERIES 320D'  →  model='3 SERIES 320D'

The CRSP source data stores the make name inside the model string for BMW
entries. This script strips that prefix so the matcher sees clean model names.

Usage
-----
    python scripts/fix_bmw_model_duplicates.py              # dry-run (no changes)
    python scripts/fix_bmw_model_duplicates.py --execute    # applies the UPDATE
"""

from __future__ import annotations

import argparse
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sqlalchemy import text
from db import engine


def _count_affected(conn) -> int:
    return int(conn.execute(text(
        "SELECT COUNT(*) FROM vehicle_years "
        "WHERE UPPER(TRIM(make)) = 'BMW' "
        "AND UPPER(TRIM(model)) LIKE 'BMW %'"
    )).scalar() or 0)


def _preview_rows(conn) -> list:
    return conn.execute(text(
        "SELECT id, make, model FROM vehicle_years "
        "WHERE UPPER(TRIM(make)) = 'BMW' "
        "AND UPPER(TRIM(model)) LIKE 'BMW %' "
        "ORDER BY model LIMIT 25"
    )).fetchall()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strip redundant 'BMW ' prefix from model column where make='BMW'."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually apply the UPDATE. Without this flag, only a dry-run is shown.",
    )
    args = parser.parse_args()

    with engine.connect() as conn:
        count = _count_affected(conn)
        rows  = _preview_rows(conn)

    print("=" * 60)
    print("  FIX BMW MODEL DUPLICATES — DRY RUN" if not args.execute else
          "  FIX BMW MODEL DUPLICATES — EXECUTING")
    print("=" * 60)
    print(f"\nRows with redundant 'BMW ' prefix: {count:,}\n")

    if count == 0:
        print("Nothing to fix.\n")
        return

    print(f"{'ID':>8}  {'Current model':<45}  After fix")
    print("-" * 75)
    for row in rows:
        fixed = row.model[4:].strip()
        print(f"{row.id:>8}  {row.model:<45}  {fixed}")
    if count > 25:
        print(f"  ... and {count - 25} more rows not shown")

    if not args.execute:
        print(f"\n[DRY RUN] No changes made. Re-run with --execute to apply.\n")
        return

    print("\nApplying UPDATE...")
    try:
        with engine.begin() as conn:
            result = conn.execute(text(
                "UPDATE vehicle_years "
                "SET model = TRIM(SUBSTRING(model FROM 5)) "
                "WHERE UPPER(TRIM(make)) = 'BMW' "
                "AND UPPER(TRIM(model)) LIKE 'BMW %'"
            ))

        print(f"\n  DONE — updated {result.rowcount:,} row(s). Changes committed.\n")

    except Exception as exc:
        print(f"\n  ERROR — transaction rolled back: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
