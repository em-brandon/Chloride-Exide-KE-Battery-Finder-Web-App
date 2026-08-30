"""
quarantine_anachronistic_years.py
---------------------------------
Remove vehicle_years rows whose own model name proves the year is wrong.

Unlike every other pass in this cleanup, this one needs no external source:
the contradiction is internal to the row. A trim named "X-DYNAMIC" cannot
carry a 1990 year, because Land Rover introduced that trim in 2020. The
model string and the year disagree, and the model string comes from CRSP —
the authoritative record of which vehicle this is — so the year is what's
wrong.

WHY THIS IS STILL NEEDED AFTER THE OTHER PASSES
-----------------------------------------------
Every source-based pass works at NAMEPLATE level. The Defender nameplate
genuinely spans 1990-2026, so a "DEFENDER T/C 5 DOOR 300PS X-DYNAMIC" row
dated 1990 looked entirely plausible to them — only the trim gives it away.
Measured after the ja.wikipedia and oem_fitment passes had run, 5,004 rows
still carried this contradiction, 4,212 of them Land Rover. These are also
the most visibly wrong rows in any export: spotting "1990 Defender
X-Dynamic" needs no domain knowledge at all.

THE DATE TABLE IS THE WHOLE RISK
--------------------------------
Everything here rests on ANACHRONISMS being right. Each entry is the first
model year the badge/trim/technology existed anywhere; a date set too late
deletes real rows. They are deliberately conservative (the earliest global
introduction, not the local launch), and only unambiguous, well-dated badges
are listed — no general trim words like "SPORT" or "LUXURY", which recur
across decades.

Rows are moved to vehicle_years_unverifiable, not deleted, so any date that
turns out to be wrong can be restored per batch.

Usage (run from backend/)
-------------------------
    python scripts/quarantine_anachronistic_years.py
    python scripts/quarantine_anachronistic_years.py --make LANDROVER
    python scripts/quarantine_anachronistic_years.py --execute
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sqlalchemy import text

import db_backup
from db import engine
from pipelines.model_name_utils import extract_base_model

SCRIPT_NAME = "quarantine_anachronistic_years.py"

# Badge / trim / powertrain names and the first model year each existed.
# Confirmed with the project owner before first use.
ANACHRONISMS = {
    # Powertrain badges
    "HYBRID":    1997,   # Toyota Prius, first mass-produced hybrid
    "E:HEV":     2018,   # Honda
    "E-POWER":   2016,   # Nissan
    "PHEV":      2010,
    "PHV":       2012,
    "MHEV":      2016,   # mild-hybrid badging
    # Engine-family badges
    "TFSI":      2004,   # Audi
    "TSI":       2005,   # VW group
    "SKYACTIV":  2011,   # Mazda
    "BLUETEC":   2006,   # Mercedes
    # Trim / sub-brand names
    "ALLTRACK":  2012,   # VW Passat Alltrack
    "X-DYNAMIC": 2020,   # Land Rover
    "GR":        2017,   # Toyota Gazoo Racing
    "VELAR":     2017,   # Range Rover Velar
    "N-BOX":     2011,   # Honda
    "EYESIGHT":  2010,   # Subaru driver-assist branding
}

# Tokens are matched whole, so "GR" never fires inside "GRACE" or "GRAND".
_TOKEN_RE = re.compile(r"[A-Z0-9:\-]{2,}")


def anachronism(model: str, year: int):
    """Return (badge, earliest_year) when the model names something that did
    not exist in `year`, else None."""
    tokens = set(_TOKEN_RE.findall(model.upper()))
    for badge, earliest in ANACHRONISMS.items():
        if badge in tokens and year < earliest:
            return badge, earliest
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true", help="Apply. Default is a dry run.")
    p.add_argument("--make", default=None, help="Restrict to one make.")
    args = p.parse_args()

    with engine.connect() as conn:
        q = ("SELECT id, make, model, year, engine_capacity, fuel, source, model_number"
             " FROM vehicle_years")
        params = {}
        if args.make:
            q += " WHERE upper(make) = upper(:mk)"
            params["mk"] = args.make
        rows = conn.execute(text(q), params).fetchall()

    hits = []
    variant_total = defaultdict(int)
    variant_hit = defaultdict(int)
    for r in rows:
        variant_total[(r.make, r.model)] += 1
        found = anachronism(r.model, r.year)
        if found:
            hits.append((r, found[0], found[1]))
            variant_hit[(r.make, r.model)] += 1

    emptied = [k for k, n in variant_hit.items() if n == variant_total[k]]

    print("=" * 74)
    print("  QUARANTINE ANACHRONISTIC YEARS —", "EXECUTING" if args.execute else "DRY RUN")
    print("=" * 74)
    print(f"\nRows scanned                : {len(rows)}")
    print(f"Rows contradicting their trim: {len(hits)}")
    print(f"Variants left with no years : {len(emptied)}\n")

    by_make = defaultdict(int)
    by_badge = defaultdict(int)
    for r, badge, _e in hits:
        by_make[r.make] += 1
        by_badge[badge] += 1
    print(f"{'MAKE':<20} {'rows':>6}")
    for make, n in sorted(by_make.items(), key=lambda x: -x[1]):
        print(f"  {make:<18} {n:>6}")
    print(f"\n{'BADGE':<14} {'from':>6} {'rows':>7}")
    for badge, n in sorted(by_badge.items(), key=lambda x: -x[1]):
        print(f"  {badge:<12} {ANACHRONISMS[badge]:>6} {n:>7}")

    if emptied:
        print(f"\nVariants that will have NO years afterwards ({len(emptied)}):")
        for make, model in sorted(emptied)[:15]:
            print(f"   {make:<12} {model[:50]}")
        if len(emptied) > 15:
            print(f"   ... and {len(emptied) - 15} more")

    if not args.execute:
        print("\n[DRY RUN] Nothing moved. Re-run with --execute to apply.\n")
        return
    if not hits:
        print("\nNothing to move.\n")
        return

    print("\nTaking a backup before applying...")
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        try:
            result = db_backup.create_backup()
            conn.execute(text(
                "INSERT INTO admin_backup_log (filename, size_bytes, status, error_detail,"
                " triggered_by, created_at) VALUES (:f, :s, 'success', NULL, :t, :c)"
            ), {"f": result.filename, "s": result.size_bytes, "t": SCRIPT_NAME, "c": now})
            print(f"  Backup created: {result.filename} ({result.size_bytes:,} bytes)")
        except db_backup.BackupError as exc:
            conn.execute(text(
                "INSERT INTO admin_backup_log (filename, size_bytes, status, error_detail,"
                " triggered_by, created_at) VALUES ('', NULL, 'failed', :e, :t, :c)"
            ), {"e": str(exc), "t": SCRIPT_NAME, "c": now})
            print(f"\n  ERROR — backup failed, aborting:\n  {exc}\n")
            sys.exit(1)

    batch_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    moved = 0
    with engine.begin() as conn:
        max_ver = conn.execute(text(
            "SELECT COALESCE(MAX(version_number), 0) FROM vehicle_years_versions")).scalar() or 0
        conn.execute(text(
            "INSERT INTO vehicle_years_versions (id, version_number, committed_at, run_id,"
            " committed_count, updated_count, removed_count, conflict_count, committed_by,"
            " initiated_by, notes) VALUES (:id, :vn, :now, :batch, 0, 0, 0, 0, :by, :by, :notes)"
        ), {"id": version_id, "vn": max_ver + 1, "now": now, "batch": batch_id,
            "by": SCRIPT_NAME,
            "notes": f"Moved rows whose trim name postdates their year, batch {batch_id}"})

        for r, badge, earliest in hits:
            conn.execute(text(
                "INSERT INTO vehicle_years_unverifiable (make, model, year, engine_capacity,"
                " fuel, source, model_number, base_model, reason, moved_at, batch_id)"
                " VALUES (:mk, :md, :yr, :ec, :fuel, :src, :mn, :base, :reason, :now, :batch)"
                " ON CONFLICT DO NOTHING"
            ), {"mk": r.make, "md": r.model, "yr": r.year, "ec": r.engine_capacity,
                "fuel": r.fuel, "src": r.source, "mn": r.model_number,
                "base": extract_base_model(r.make, r.model),
                "reason": f"anachronism|{badge}-from-{earliest}", "now": now, "batch": batch_id})
            conn.execute(text("DELETE FROM vehicle_years WHERE id = :id"), {"id": r.id})
            conn.execute(text(
                "INSERT INTO vehicle_years_changelog (version_id, make, model, year,"
                " change_type, old_values, new_values)"
                " VALUES (:vid, :mk, :md, :yr, 'removed', :old, NULL)"
            ), {"vid": version_id, "mk": r.make, "md": r.model, "yr": r.year,
                "old": json.dumps({"engine_capacity": r.engine_capacity, "fuel": r.fuel,
                                   "source": r.source})})
            moved += 1

        conn.execute(text(
            "UPDATE vehicle_years_versions SET removed_count = :n WHERE id = :id"),
            {"n": moved, "id": version_id})

    print(f"\n  DONE")
    print(f"    Moved:    {moved:,} rows -> vehicle_years_unverifiable")
    print(f"    Batch ID: {batch_id}")
    print(f"    Version:  {version_id} (revertible via the admin UI)")
    print(f"\n  To undo: python scripts/quarantine_unverifiable_years.py "
          f"--restore {batch_id} --execute\n")


if __name__ == "__main__":
    main()
