"""
fix_bmw_model_duplicates.py
---------------------------
Removes the redundant 'BMW ' prefix from the model column in vehicle_years
where make is already 'BMW'.

Two-phase approach to handle unique-constraint conflicts:
  1. DELETE rows whose clean name already exists in the table (true duplicates).
  2. UPDATE the remaining prefixed rows to the clean name.

Both phases run in a single transaction.

Usage
-----
    python scripts/fix_bmw_model_duplicates.py              # dry-run
    python scripts/fix_bmw_model_duplicates.py --execute    # apply changes
"""

from __future__ import annotations

import argparse
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sqlalchemy import text
from db import engine

# ── SQL ───────────────────────────────────────────────────────────────────────

# Rows with the redundant "BMW " prefix
_BASE_WHERE = (
    "UPPER(TRIM(make)) = 'BMW' "
    "AND UPPER(TRIM(model)) LIKE 'BMW %'"
)

# Phase 1: rows whose clean counterpart ALREADY exists → safe to delete
_DELETE_SQL = text(f"""
    DELETE FROM vehicle_years
    WHERE {_BASE_WHERE}
      AND EXISTS (
          SELECT 1 FROM vehicle_years v2
          WHERE  v2.make  = vehicle_years.make
          AND    v2.model = TRIM(SUBSTRING(vehicle_years.model FROM 5))
          AND    v2.year  = vehicle_years.year
      )
""")

# Phase 2: rename remaining prefixed rows (no conflict possible after phase 1)
_UPDATE_SQL = text(f"""
    UPDATE vehicle_years
    SET    model = TRIM(SUBSTRING(model FROM 5))
    WHERE  {_BASE_WHERE}
""")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _count_total(conn) -> int:
    return int(conn.execute(text(
        f"SELECT COUNT(*) FROM vehicle_years WHERE {_BASE_WHERE}"
    )).scalar() or 0)


def _count_to_delete(conn) -> int:
    return int(conn.execute(text(f"""
        SELECT COUNT(*) FROM vehicle_years
        WHERE  {_BASE_WHERE}
          AND  EXISTS (
              SELECT 1 FROM vehicle_years v2
              WHERE  v2.make  = vehicle_years.make
              AND    v2.model = TRIM(SUBSTRING(vehicle_years.model FROM 5))
              AND    v2.year  = vehicle_years.year
          )
    """)).scalar() or 0)


def _preview(conn, limit: int = 25) -> list:
    return conn.execute(text(f"""
        SELECT id, model,
               TRIM(SUBSTRING(model FROM 5)) AS clean,
               EXISTS (
                   SELECT 1 FROM vehicle_years v2
                   WHERE  v2.make  = vehicle_years.make
                   AND    v2.model = TRIM(SUBSTRING(vehicle_years.model FROM 5))
                   AND    v2.year  = vehicle_years.year
               ) AS is_duplicate
        FROM   vehicle_years
        WHERE  {_BASE_WHERE}
        ORDER  BY model
        LIMIT  {limit}
    """)).fetchall()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strip redundant 'BMW ' prefix from model column where make='BMW'."
    )
    parser.add_argument("--execute", action="store_true",
                        help="Apply changes. Without this flag only a dry-run is shown.")
    args = parser.parse_args()

    with engine.connect() as conn:
        total      = _count_total(conn)
        to_delete  = _count_to_delete(conn)
        to_update  = total - to_delete
        rows       = _preview(conn)

    print("=" * 68)
    print("  FIX BMW MODEL DUPLICATES —", "EXECUTING" if args.execute else "DRY RUN")
    print("=" * 68)
    print(f"\nRows with redundant 'BMW ' prefix : {total:>5}")
    print(f"  → Phase 1 DELETE (clean already exists): {to_delete:>5}")
    print(f"  → Phase 2 UPDATE (rename to clean name): {to_update:>5}\n")

    if total == 0:
        print("Nothing to fix.\n")
        return

    print(f"{'ID':>8}  {'Action':<8}  {'Current model':<45}  After")
    print("-" * 85)
    for row in rows:
        action = "DELETE" if row.is_duplicate else "UPDATE"
        print(f"{row.id:>8}  {action:<8}  {row.model:<45}  {row.clean}")
    if total > 25:
        print(f"  ... and {total - 25} more rows not shown")

    if not args.execute:
        print(f"\n[DRY RUN] No changes made. Re-run with --execute to apply.\n")
        return

    print("\nApplying changes in one transaction …")
    try:
        with engine.begin() as conn:
            del_result = conn.execute(_DELETE_SQL)
            upd_result = conn.execute(_UPDATE_SQL)

        print(f"\n  DONE")
        print(f"    Deleted : {del_result.rowcount:,} duplicate rows")
        print(f"    Updated : {upd_result.rowcount:,} rows renamed")
        print(f"    Total   : {del_result.rowcount + upd_result.rowcount:,} rows affected\n")

    except Exception as exc:
        print(f"\n  ERROR — transaction rolled back:\n  {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
