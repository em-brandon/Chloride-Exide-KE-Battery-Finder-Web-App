"""
cleanup_non_kenya_makes.py
--------------------------
Removes non-Kenyan vehicle makes from vehicle_years and web_battery_validation.

Based on cross-referencing 57,816 Dial-A-Battery Kenyan orders (2023–2026) with
external market research (94.3% of Kenya used-car imports from Japan; European/
American brands under 3% combined). Makes with near-zero real Kenyan orders are
removed to reduce the pipeline's ~14,000 Phase 1 buckets.

Additionally trims AUDI to 2010+ only (177 actual Kenyan orders but 2,613 pipeline
entries spanning old model years nobody in Kenya drives).

Usage
-----
    python scripts/cleanup_non_kenya_makes.py              # dry-run (no changes)
    python scripts/cleanup_non_kenya_makes.py --execute    # performs the deletes
"""

from __future__ import annotations

import argparse
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sqlalchemy import text
from db import engine

# ---------------------------------------------------------------------------
# Makes to remove entirely
# ---------------------------------------------------------------------------
REMOVE_MAKES: set[str] = {
    # Definite removes — 0–4 Kenyan battery orders in 3 years of sales data
    "BENTLEY",
    "FERRARI",
    "BRABUS",       # German tuner brand, not a real OEM make
    "CADILLAC",
    "CHRYSLER",
    "CITROEN",
    "GEELY",
    "IVECO DAILY",
    "ALFA ROMEO",
    # Strong removes — 5–25 orders, negligible Kenya market presence
    "FOTON",
    "SKODA",
    "OPEL",
    "PROTON",
}

AUDI_MIN_YEAR = 2010   # keep AUDI 2010 and later; remove older entries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_exists(conn, table: str) -> bool:
    row = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_name = :t)"
    ), {"t": table}).scalar()
    return bool(row)


def _count_vehicle_years_removes(conn) -> tuple[int, int]:
    """Returns (full_remove_count, audi_pre_2010_count)."""
    makes_list = list(REMOVE_MAKES)
    full = conn.execute(text(
        "SELECT COUNT(*) FROM vehicle_years "
        "WHERE UPPER(TRIM(make)) = ANY(:makes)"
    ), {"makes": makes_list}).scalar() or 0

    audi = conn.execute(text(
        "SELECT COUNT(*) FROM vehicle_years "
        "WHERE UPPER(TRIM(make)) = 'AUDI' AND year < :min_year"
    ), {"min_year": AUDI_MIN_YEAR}).scalar() or 0

    return int(full), int(audi)


def _count_web_validation_removes(conn) -> tuple[int, int]:
    """Returns (full_remove_count, audi_pre_2010_count). Returns (0, 0) if table absent."""
    if not _table_exists(conn, "web_battery_validation"):
        return 0, 0

    makes_list = list(REMOVE_MAKES)
    full = conn.execute(text(
        "SELECT COUNT(*) FROM web_battery_validation "
        "WHERE make_n = ANY(:makes)"
    ), {"makes": makes_list}).scalar() or 0

    audi = conn.execute(text(
        "SELECT COUNT(*) FROM web_battery_validation "
        "WHERE make_n = 'AUDI' AND year < :min_year"
    ), {"min_year": AUDI_MIN_YEAR}).scalar() or 0

    return int(full), int(audi)


def _total_vehicle_years(conn) -> int:
    return int(conn.execute(text("SELECT COUNT(*) FROM vehicle_years")).scalar() or 0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove non-Kenyan vehicle makes from the database."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the deletes. Without this flag, only a dry-run is shown.",
    )
    args = parser.parse_args()

    with engine.connect() as conn:
        total_before = _total_vehicle_years(conn)
        vy_full, vy_audi = _count_vehicle_years_removes(conn)
        wbv_full, wbv_audi = _count_web_validation_removes(conn)

    vy_total_remove  = vy_full + vy_audi
    wbv_total_remove = wbv_full + wbv_audi

    print("=" * 60)
    print("  CLEANUP NON-KENYA MAKES — DRY RUN" if not args.execute else
          "  CLEANUP NON-KENYA MAKES — EXECUTING")
    print("=" * 60)
    print(f"\nvehicle_years rows before  : {total_before:,}")
    print(f"\n  Full removes ({len(REMOVE_MAKES)} makes)   : {vy_full:,} rows")
    print(f"  AUDI pre-{AUDI_MIN_YEAR}             : {vy_audi:,} rows")
    print(f"  Total to remove           : {vy_total_remove:,} rows")
    print(f"  Rows remaining (est.)     : {total_before - vy_total_remove:,}")
    print(f"\nweb_battery_validation")
    print(f"  Full removes              : {wbv_full:,} rows")
    print(f"  AUDI pre-{AUDI_MIN_YEAR}             : {wbv_audi:,} rows")
    print(f"  Total to remove           : {wbv_total_remove:,} rows")

    print(f"\nMakes removed entirely:")
    for m in sorted(REMOVE_MAKES):
        print(f"  - {m}")
    print(f"\nAUDI: keeping year >= {AUDI_MIN_YEAR} only")

    if not args.execute:
        print("\n[DRY RUN] No changes made. Re-run with --execute to apply.\n")
        return

    print("\nProceeding with deletes...")
    makes_list = list(REMOVE_MAKES)

    try:
        with engine.begin() as conn:   # auto-commits on success, rolls back on exception
            # --- vehicle_years ---
            r1 = conn.execute(text(
                "DELETE FROM vehicle_years WHERE UPPER(TRIM(make)) = ANY(:makes)"
            ), {"makes": makes_list})

            r2 = conn.execute(text(
                "DELETE FROM vehicle_years "
                "WHERE UPPER(TRIM(make)) = 'AUDI' AND year < :min_year"
            ), {"min_year": AUDI_MIN_YEAR})

            # --- web_battery_validation (skip if table absent) ---
            wbv_deleted_full = 0
            wbv_deleted_audi = 0
            with engine.connect() as chk:
                wbv_exists = _table_exists(chk, "web_battery_validation")

            if wbv_exists:
                r3 = conn.execute(text(
                    "DELETE FROM web_battery_validation WHERE make_n = ANY(:makes)"
                ), {"makes": makes_list})
                wbv_deleted_full = r3.rowcount

                r4 = conn.execute(text(
                    "DELETE FROM web_battery_validation "
                    "WHERE make_n = 'AUDI' AND year < :min_year"
                ), {"min_year": AUDI_MIN_YEAR})
                wbv_deleted_audi = r4.rowcount

        # Verify after commit
        with engine.connect() as conn:
            total_after = _total_vehicle_years(conn)

        print("\n  DONE")
        print(f"  vehicle_years deleted     : {r1.rowcount + r2.rowcount:,} rows")
        print(f"    (full removes: {r1.rowcount:,}, AUDI pre-{AUDI_MIN_YEAR}: {r2.rowcount:,})")
        print(f"  web_battery_validation    : {wbv_deleted_full + wbv_deleted_audi:,} rows")
        print(f"  vehicle_years rows after  : {total_after:,}\n")

    except Exception as exc:
        print(f"\n  ERROR — transaction rolled back: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
