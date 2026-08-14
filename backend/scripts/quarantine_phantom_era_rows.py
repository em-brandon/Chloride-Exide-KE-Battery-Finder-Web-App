"""
quarantine_phantom_era_rows.py
------------------------------
Final automated pass over the year data: move pre-1990 rows belonging to
nameplates no automated source could date into vehicle_years_unverifiable,
unless an independent source vouches for the vehicle existing that early.

THE ARGUMENT FOR A DATE FLOOR
-----------------------------
This is a statistical judgement, not per-vehicle proof, so the evidence for
it is worth stating plainly. Of the 4,829 rows in nameplates ja.wikipedia
did successfully verify, only 7 — 0.14% — turned out to genuinely predate
1990. In this catalogue a pre-1990 year is almost always an artifact of the
defects being cleaned up (unbounded Wikidata inception dates, dataset floors
leaking through as real values), all of which pushed years too far into the
past. CRSP is a current-vehicle price schedule; it is not cataloguing 1960s
trucks.

The unverified remainder holds 3,136 pre-1990 rows. On that base rate they
are overwhelmingly wrong, and they are the last large block of bad data
reachable without manual research.

The base rate is optimistic, though: ja.wikipedia resolves modern JDM
passenger cars best, so the verified sample skews modern and genuinely old
commercial vehicles are under-represented in it. Hence the exemption below,
and hence moving rows rather than deleting them.

EXEMPTION
---------
Before moving anything for a nameplate, oem_fitment / fueleconomy_vehicles /
web_battery_validation are checked for a year range covering the pre-1990
era. If one vouches for the vehicle existing then, the whole nameplate is
skipped — that is how a genuine 1980s truck, or a Land Cruiser 80 (1989-),
avoids being caught by a blanket floor.

NOT A DELETION
--------------
Every row moved is copied into vehicle_years_unverifiable first, carrying
its nameplate and the reason, so the table doubles as the manual-research
worklist and `--restore BATCH_ID` puts any batch back verbatim. A
vehicle_years_versions / vehicle_years_changelog entry is written as well,
so the admin UI revert works exactly as for every other pass.

Variants left with no years at all
----------------------------------
89 variants hold nothing BUT pre-1990 rows and disappear from the year
dropdown when those move. They were already non-functional: HONDA N-B0X EX
is stored as 1976-1989 while the N-BOX launched in 2011, so a customer with
a real one is offered only impossible years today. This removes coverage
that never worked rather than coverage that did — but it is a real change to
what the dropdown shows, so the report lists them explicitly before applying.

Usage (run from backend/)
-------------------------
    python scripts/quarantine_phantom_era_rows.py --residue-dir DIR
    python scripts/quarantine_phantom_era_rows.py --residue-dir DIR --execute
    python scripts/quarantine_unverifiable_years.py --restore BATCH_ID --execute
"""

from __future__ import annotations

import argparse
import json
import os
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
from scripts.quarantine_unverifiable_years import (
    corroborating_source, load_residue)

SCRIPT_NAME = "quarantine_phantom_era_rows.py"
PHANTOM_FLOOR = 1990


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--residue-dir", required=True,
                   help="Directory of fix_vehicle_years_phantom_dates.py per-make logs.")
    p.add_argument("--execute", action="store_true", help="Apply. Default is a dry run.")
    p.add_argument("--make", default=None, help="Restrict to one make.")
    p.add_argument("--floor", type=int, default=PHANTOM_FLOOR,
                   help=f"Year floor (default {PHANTOM_FLOOR}).")
    args = p.parse_args()

    residue = load_residue(args.residue_dir)
    if args.make:
        residue = {k: v for k, v in residue.items() if k[0].upper() == args.make.upper()}
    if not residue:
        print("No residue nameplates matched.")
        return

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, make, model, year, engine_capacity, fuel, source, model_number"
            " FROM vehicle_years")).fetchall()

        variant_rows = defaultdict(list)
        for r in rows:
            variant_rows[(r.make, r.model)].append(r)

        # Which nameplates have an independent source covering the pre-floor era?
        exempt = {}
        checked = set()
        for r in rows:
            key = (r.make, extract_base_model(r.make, r.model))
            if key not in residue or key in checked:
                continue
            checked.add(key)
            corr = corroborating_source(conn, key[0], key[1])
            if corr and corr[1] < args.floor:
                exempt[key] = corr

        moves = []          # (row, base_model)
        emptied = []        # (make, model, lo, hi, n)
        for (make, model), rs in variant_rows.items():
            key = (make, extract_base_model(make, model))
            if key not in residue or key in exempt:
                continue
            below = [r for r in rs if r.year < args.floor]
            if not below:
                continue
            moves.extend((r, key[1]) for r in below)
            if len(below) == len(rs):
                yrs = [r.year for r in rs]
                emptied.append((make, model, min(yrs), max(yrs), len(rs)))

    print("=" * 74)
    print("  QUARANTINE PHANTOM-ERA ROWS —", "EXECUTING" if args.execute else "DRY RUN")
    print("=" * 74)
    print(f"\nYear floor                   : {args.floor}")
    print(f"Residue nameplates           : {len(residue)}")
    print(f"  exempt (source vouches)    : {len(exempt)}")
    print(f"Rows to move                 : {len(moves)}")
    print(f"Variants left with no years  : {len(emptied)}\n")

    by_make = defaultdict(lambda: [0, set(), 0])
    for r, _base in moves:
        by_make[r.make][0] += 1
        by_make[r.make][1].add(r.model)
    for make, model, *_ in emptied:
        by_make[make][2] += 1
    print(f"{'MAKE':<20} {'rows':>7} {'variants':>9} {'emptied':>8}")
    for make, (n, variants, emp) in sorted(by_make.items(), key=lambda x: -x[1][0]):
        print(f"  {make:<18} {n:>7} {len(variants):>9} {emp:>8}")

    if exempt:
        print(f"\nExempt nameplates ({len(exempt)}) — an independent source covers the pre-{args.floor} era:")
        for (make, base), (src, lo, hi) in sorted(exempt.items())[:20]:
            print(f"   {make:<12} {base:<28} {src} says {lo}-{hi}")
        if len(exempt) > 20:
            print(f"   ... and {len(exempt) - 20} more")

    if emptied:
        print(f"\nVariants that will have NO years afterwards ({len(emptied)}):")
        for make, model, lo, hi, n in sorted(emptied)[:25]:
            print(f"   {make:<12} {model:<38} {lo}-{hi} ({n} rows)")
        if len(emptied) > 25:
            print(f"   ... and {len(emptied) - 25} more")

    if not args.execute:
        print("\n[DRY RUN] Nothing moved. Re-run with --execute to apply.\n")
        return
    if not moves:
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
            "notes": f"Moved pre-{args.floor} rows of unverifiable nameplates to "
                     f"vehicle_years_unverifiable, batch {batch_id}"})

        for r, base in moves:
            reason = f"{residue[(r.make, base)]}|pre-{args.floor}"
            conn.execute(text(
                "INSERT INTO vehicle_years_unverifiable (make, model, year, engine_capacity,"
                " fuel, source, model_number, base_model, reason, moved_at, batch_id)"
                " VALUES (:mk, :md, :yr, :ec, :fuel, :src, :mn, :base, :reason, :now, :batch)"
                " ON CONFLICT DO NOTHING"
            ), {"mk": r.make, "md": r.model, "yr": r.year, "ec": r.engine_capacity,
                "fuel": r.fuel, "src": r.source, "mn": r.model_number, "base": base,
                "reason": reason, "now": now, "batch": batch_id})
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
