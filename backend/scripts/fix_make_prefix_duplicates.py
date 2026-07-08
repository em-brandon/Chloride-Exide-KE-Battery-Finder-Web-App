"""
fix_make_prefix_duplicates.py
------------------------------
Removes the redundant '{MAKE} ' prefix from the model column in vehicle_years
wherever model already starts with its own make, for any make (not just BMW —
supersedes the narrower fix_bmw_model_duplicates.py, which only covered BMW
and left the same bug live for SUBARU, MAZDA, SCANIA, TATA, TOYOTA, FIAT,
ISUZU, GREAT WALL and VOLVO).

Two-phase approach to handle unique-constraint conflicts (uq_vehicle_years on
make/model/year):
  1. DELETE rows whose clean name already exists for that make+year (true duplicates).
  2. UPDATE the remaining prefixed rows to the clean name.

Both phases run in a single transaction. Rows where stripping the prefix would
leave an empty model (model consists of only the make) are left untouched.

Usage
-----
    python scripts/fix_make_prefix_duplicates.py              # dry-run
    python scripts/fix_make_prefix_duplicates.py --execute    # apply changes
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

# Rows whose model redundantly repeats their own make as a prefix, excluding
# any row where stripping would leave an empty model.
_BASE_WHERE = (
    "UPPER(TRIM(model)) LIKE UPPER(TRIM(make)) || ' %' "
    "AND LENGTH(TRIM(SUBSTRING(model FROM LENGTH(TRIM(make)) + 2))) > 0"
)

_CLEAN_EXPR = "TRIM(SUBSTRING(vehicle_years.model FROM LENGTH(TRIM(vehicle_years.make)) + 2))"

# Phase 1: rows whose clean counterpart ALREADY exists → safe to delete
_DELETE_SQL = text(f"""
    DELETE FROM vehicle_years
    WHERE {_BASE_WHERE}
      AND EXISTS (
          SELECT 1 FROM vehicle_years v2
          WHERE  v2.make  = vehicle_years.make
          AND    v2.model = {_CLEAN_EXPR}
          AND    v2.year  = vehicle_years.year
      )
""")

# Phase 2: rename remaining prefixed rows (no conflict possible after phase 1)
_UPDATE_SQL = text(f"""
    UPDATE vehicle_years
    SET    model = TRIM(SUBSTRING(model FROM LENGTH(TRIM(make)) + 2))
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
              AND    v2.model = {_CLEAN_EXPR}
              AND    v2.year  = vehicle_years.year
          )
    """)).scalar() or 0)


def _by_make(conn) -> list:
    return conn.execute(text(f"""
        SELECT make, COUNT(*) AS n
        FROM   vehicle_years
        WHERE  {_BASE_WHERE}
        GROUP  BY make
        ORDER  BY n DESC
    """)).fetchall()


def _preview(conn, limit: int = 30) -> list:
    return conn.execute(text(f"""
        SELECT id, make, model,
               {_CLEAN_EXPR} AS clean,
               EXISTS (
                   SELECT 1 FROM vehicle_years v2
                   WHERE  v2.make  = vehicle_years.make
                   AND    v2.model = {_CLEAN_EXPR}
                   AND    v2.year  = vehicle_years.year
               ) AS is_duplicate
        FROM   vehicle_years
        WHERE  {_BASE_WHERE}
        ORDER  BY make, model
        LIMIT  {limit}
    """)).fetchall()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strip redundant '{MAKE} ' prefix from model for any make."
    )
    parser.add_argument("--execute", action="store_true",
                        help="Apply changes. Without this flag only a dry-run is shown.")
    args = parser.parse_args()

    with engine.connect() as conn:
        total      = _count_total(conn)
        to_delete  = _count_to_delete(conn)
        to_update  = total - to_delete
        by_make    = _by_make(conn)
        rows       = _preview(conn)

    print("=" * 68)
    print("  FIX MAKE-PREFIX MODEL DUPLICATES —", "EXECUTING" if args.execute else "DRY RUN")
    print("=" * 68)
    print(f"\nRows with redundant '{{MAKE}} ' prefix : {total:>5}")
    print(f"  → Phase 1 DELETE (clean already exists): {to_delete:>5}")
    print(f"  → Phase 2 UPDATE (rename to clean name): {to_update:>5}\n")

    if total == 0:
        print("Nothing to fix.\n")
        return

    print("By make:")
    for row in by_make:
        print(f"  {row.make:<12} {row.n:>5}")

    print(f"\n{'ID':>8}  {'Action':<8}  {'Make':<12}  {'Current model':<45}  After")
    print("-" * 95)
    for row in rows:
        action = "DELETE" if row.is_duplicate else "UPDATE"
        print(f"{row.id:>8}  {action:<8}  {row.make:<12}  {row.model:<45}  {row.clean}")
    if total > 30:
        print(f"  ... and {total - 30} more rows not shown")

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
