"""
normalise_fuel_labels.py
------------------------
Write the canonical fuel label into vehicle_years and web_battery_validation.

THE PROBLEM
-----------
CRSP carries one concept under many spellings, and the export prints the raw
value:

    GASOLINE 17,874   PETROL 7,057      same thing, two words
    DEISEL       84   ELECCTRIC   37    typos in the source
    "40"         31   "37"        24    an Ah value in the fuel column
    (empty)      15

The duplicates and typos are cosmetic but land in a client-facing fitment
guide, where "GASOLINE" and "PETROL" as separate fuel types — and a literal
"40" — read as a broken export.

WHY THIS IS BEHAVIOUR-NEUTRAL
-----------------------------
matcher._norm_fuel() already collapses every one of these through _FUEL_MAP
before any rule sees it, defaulting anything unrecognised to PETROL. So the
matcher has always treated GASOLINE as PETROL and "40" as PETROL. This writes
that same resolved value back to the column instead of leaving the raw string
sitting there for the export to print. No recommendation changes.

THE NUMERIC VALUES ARE NOT GUESSES
----------------------------------
"40" and "37" are Ah figures shifted into the wrong column — every affected row
is a 658 cc kei car, and 40Ah is the correct battery for one. The blank rows
are Hyundai i30 N, a petrol-only hot hatch at 2000 cc. Both resolve to PETROL
on the evidence rather than by defaulting: kei cars are not sold as diesels and
the i30 N has no diesel variant. They land on PETROL, which is also what
_norm_fuel already returned for them, so the value is unchanged in effect and
merely made explicit.

Usage (run from backend/)
-------------------------
    python scripts/normalise_fuel_labels.py
    python scripts/normalise_fuel_labels.py --execute
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
from sqlalchemy import text

import db_backup
from db import engine
from matcher import _norm_fuel

SCRIPT = "normalise_fuel_labels.py"
TARGETS = [("vehicle_years", "fuel"), ("web_battery_validation", "fuel_type")]

# REPAIRS ONLY — not matcher._FUEL_MAP.
#
# _FUEL_MAP is a *matching* map: it deliberately collapses PLUG-IN HYBRID into
# HYBRID and PETROL/ELECTRIC into PETROL because the Ah and technology rules do
# not distinguish them. Writing that collapse back into the column would
# destroy information the export should keep — a reader looking at a fitment
# guide wants to see that a car is a plug-in hybrid, and once overwritten the
# distinction cannot be recovered.
#
# So only three classes are touched, all of which are unambiguously damage:
#   * spelling errors in the source  (DEISEL, ELECCTRIC)
#   * a synonym carrying no extra meaning (GASOLINE is PETROL, full stop)
#   * values that are not fuels at all (an Ah figure shifted into the column,
#     and blanks) — see the module docstring for why these resolve to PETROL
#     on the evidence rather than by defaulting.
_REPAIRS: dict[str | None, str] = {
    "GASOLINE": "PETROL",
    "DEISEL": "DIESEL",
    "ELECCTRIC": "ELECTRIC(EV)",
    "37": "PETROL",
    "40": "PETROL",
    "": "PETROL",
    None: "PETROL",
}


def repair(raw):
    """Canonical value for a damaged fuel label, or None to leave it alone."""
    if raw is None:
        return _REPAIRS[None]
    return _REPAIRS.get(str(raw).strip().upper())


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    plans = []
    for table, col in TARGETS:
        with engine.connect() as conn:
            df = pd.read_sql(f"SELECT DISTINCT {col} AS f FROM {table}", conn)
        moves = Counter()
        for raw in df.f:
            # A SQL NULL arrives from pandas as NaN, which Postgres then refuses
            # to compare against a varchar column ("operator does not exist:
            # character varying = double precision"). Put the None back.
            if raw is not None and not isinstance(raw, str) and pd.isna(raw):
                raw = None
            canon = repair(raw)
            if canon is not None and (raw or "") != canon:
                moves[(raw, canon)] += 1
        plans.append((table, col, moves))
        print(f"\n{table}.{col}")
        if not moves:
            print("   already canonical")
            continue
        with engine.connect() as conn:
            for (raw, canon) in moves:
                n = conn.execute(text(
                    f"SELECT count(*) FROM {table} WHERE {col} IS NOT DISTINCT FROM :r"),
                    {"r": raw}).scalar()
                print(f"   {str(raw)!r:<20} -> {canon:<8} {n:>7,} rows")

    if not args.execute:
        print("\n[DRY RUN] Nothing changed. Re-run with --execute to apply.\n")
        return 0

    now = datetime.now(timezone.utc)
    try:
        res = db_backup.create_backup()
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO admin_backup_log (filename,size_bytes,status,error_detail,"
                " triggered_by,created_at) VALUES (:f,:s,'success',NULL,:t,:c)"),
                {"f": res.filename, "s": res.size_bytes, "t": SCRIPT, "c": now})
        print(f"\n  backup: {res.filename}")
    except db_backup.BackupError as exc:
        print(f"\n  ERROR — backup failed, aborting: {exc}\n")
        return 1

    total = 0
    with engine.begin() as c:
        for table, col, moves in plans:
            for (raw, canon) in moves:
                r = c.execute(text(
                    f"UPDATE {table} SET {col} = :c"
                    f" WHERE {col} IS NOT DISTINCT FROM :r"), {"c": canon, "r": raw})
                total += r.rowcount
    print(f"  DONE — {total:,} rows normalised\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
