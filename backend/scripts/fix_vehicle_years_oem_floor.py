"""
fix_vehicle_years_oem_floor.py
------------------------------
Second-pass year cleanup for nameplates ja.wikipedia could not resolve,
using `oem_fitment` (Exide's own global fitment guide, already in this
database) as the authority. No network calls — it reads a local table.

FLOOR ONLY — and why
--------------------
`oem_fitment` gives a year_from and a year_to per fitment. Only the FIRST is
trustworthy:

  * year_from is real. Exide would not publish a battery fitment for a
    vehicle that did not exist yet.
  * year_to is an artifact of when that make's data was compiled, not when
    the vehicle stopped being built. Verified against the live table: the
    guide's newest Hino entry is 2006 and its newest Daihatsu entry 2013,
    while both makes are obviously still in production.

Concretely, HINO DUTRO ALL LOW FLOOR holds 74 rows spanning 1953-2026 and
oem_fitment reports "1999-2001". Trusting both ends would keep 3 rows and
delete 71 — including all 25 genuine post-2001 rows, so a customer with a
2015 Dutro would get no recommendation at all. Trusting only the floor
deletes the 46 impossible pre-1999 rows and leaves the rest alone.

This is safe precisely because every known defect in this table pushes years
too far into the PAST (unbounded Wikidata inception dates, dataset floors
leaking through as real values). Nothing invented future years, so a
trustworthy lower bound removes the junk without ever needing the
untrustworthy upper one.

Emptied variants
----------------
A variant whose every row sits below the floor would be left with no years
at all. Where sibling variants of the same nameplate survive the cut, their
surviving years are copied across — those siblings are the same vehicle in
a different trim, so their post-floor range is real evidence. Where the
whole nameplate is below the floor there is nothing to copy from, so it is
left untouched and reported as residue rather than guessed at.

Usage (run from backend/)
-------------------------
    python scripts/fix_vehicle_years_oem_floor.py --residue-dir DIR
    python scripts/fix_vehicle_years_oem_floor.py --residue-dir DIR --make HINO
    python scripts/fix_vehicle_years_oem_floor.py --residue-dir DIR --execute

Takes a backup before applying and writes a vehicle_years_versions /
vehicle_years_changelog entry, so the pass is revertible from the admin UI
exactly like the ja.wikipedia one.
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
from pipelines.model_name_utils import extract_base_model, extract_chassis_code
from pipelines.oem_fitment_years import (
    EARLIEST_CREDIBLE_YEAR, chassis_matches, chassis_patterns)
from scripts.quarantine_unverifiable_years import load_residue

SCRIPT_NAME = "fix_vehicle_years_oem_floor.py"
SOURCE_TAG = "oem_fitment"
CURRENT_YEAR = datetime.now(timezone.utc).year

# A name/alias-tier floor is only ever "the year Exide's guide starts covering
# this nameplate", which is >= the real launch year — not equal to it. Verified
# live: the guide's earliest HINO 700 SERIES entry is 2002 while the Profia it
# maps to launched in 1992, so deleting everything below 2002 would have taken
# 10 genuine 1992-2001 rows along with the 37 phantom pre-1990 ones.
#
# So a name/alias floor is clamped to PHANTOM_FLOOR: it may only remove rows in
# the era we independently know to be junk (the unbounded-inception-date bug
# never produced years after this), never rows that could be real.
#
# A chassis-code floor is exempt — matching an exact chassis code identifies
# one generation, so the guide's year_from for it really is that generation's
# start (LEXUS ES300H -> 2018, HONDA VEZEL E:HEV -> 2021, both correct).
PHANTOM_FLOOR = 1990


def load_oem(conn, make):
    rows = conn.execute(text(
        "SELECT DISTINCT model, year_from FROM oem_fitment"
        " WHERE upper(make) = upper(:mk) AND year_from IS NOT NULL"
    ), {"mk": make}).fetchall()
    return [r for r in rows if EARLIEST_CREDIBLE_YEAR <= r.year_from <= CURRENT_YEAR]


def load_alias_names(conn, make):
    """
    JDM nameplate -> the international/export names it is also sold under.

    oem_fitment uses export naming for some makes while vehicle_years uses the
    JDM nameplate — Hino's 300/500/700 Series are the Dutro/Ranger/Profia — so
    a name-tier lookup finds nothing without this bridge. model_aliases is
    already the repo's table for that mapping, so it is read rather than
    duplicated here.
    """
    out = defaultdict(set)
    for r in conn.execute(text(
        "SELECT international_model, jdm_model FROM model_aliases"
        " WHERE upper(make) = upper(:mk)"
    ), {"mk": make}).fetchall():
        out[r.jdm_model.upper().strip()].add(r.international_model.upper().strip())
    return out


def find_floor(oem_rows, base_model, chassis_hint, alias_names=None):
    """
    Earliest credible year_from for this nameplate, or None.

    Chassis-code matches are preferred and used alone when present; they
    identify a specific generation, so mixing them with looser name matches
    would drag the floor back down to the nameplate's oldest generation and
    undo the precision.
    """
    head_needle = base_model.upper().strip()
    first_token = head_needle.split()[0] if head_needle.split() else head_needle

    if chassis_hint:
        hits = [r.year_from for r in oem_rows
                if any(chassis_matches(p, chassis_hint) for p in chassis_patterns(r.model))]
        if hits:
            return min(hits), "chassis_code"

    # The nameplate itself, plus any export name it is also sold under.
    needles = {head_needle, first_token}
    for jdm, intls in (alias_names or {}).items():
        if head_needle == jdm or head_needle.startswith(jdm + " ") or first_token == jdm:
            needles |= intls

    hits, via = [], "model_name"
    for r in oem_rows:
        head = r.model.split("(")[0].strip().upper()
        for needle in needles:
            if head == needle or head.startswith(needle + " ") or needle.startswith(head + " "):
                hits.append(r.year_from)
                if needle not in (head_needle, first_token):
                    via = "model_alias"
                break
    if hits:
        return min(hits), via
    return None, None


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--residue-dir", required=True,
                   help="Directory of fix_vehicle_years_phantom_dates.py per-make logs.")
    p.add_argument("--execute", action="store_true", help="Apply. Default is a dry run.")
    p.add_argument("--make", default=None, help="Restrict to one make.")
    p.add_argument("--crsp-file", default=None,
                   help="Raw CRSP Excel, to use model_number chassis codes for a "
                        "generation-precise floor instead of a nameplate-wide one.")
    args = p.parse_args()

    residue = load_residue(args.residue_dir)
    if args.make:
        residue = {k: v for k, v in residue.items() if k[0].upper() == args.make.upper()}
    if not residue:
        print("No residue nameplates matched.")
        return

    model_numbers = {}
    if args.crsp_file:
        import pandas as pd
        df = pd.read_excel(args.crsp_file, header=1)
        df.columns = df.columns.str.strip().str.lower().str.replace(r'[\s\n]+', '_', regex=True)
        for _, row in df.iterrows():
            mk, md = str(row.get("make", "")).strip().upper(), str(row.get("model", "")).strip().upper()
            mn = row.get("model_number")
            if mk and md and mn and str(mn).strip().lower() != "nan":
                model_numbers[(mk, md)] = str(mn).strip()

    with engine.connect() as conn:
        groups = defaultdict(lambda: defaultdict(set))
        specs = {}
        for r in conn.execute(text(
                "SELECT make, model, year, engine_capacity, fuel FROM vehicle_years")).fetchall():
            key = (r.make, extract_base_model(r.make, r.model))
            groups[key][r.model].add(r.year)
            specs.setdefault((r.make, r.model), (r.engine_capacity, r.fuel))

        oem_cache = {}
        alias_cache = {}
        plans = {}
        no_floor = []
        for key in sorted(residue):
            make, base = key
            if key not in groups:
                continue
            if make not in oem_cache:
                oem_cache[make] = load_oem(conn, make)
                alias_cache[make] = load_alias_names(conn, make)
            variants = groups[key]

            hint = None
            for v in sorted(variants):
                c = extract_chassis_code(model_numbers.get((make.upper(), v.upper())))
                if c:
                    hint = c
                    break

            floor, via = find_floor(oem_cache[make], base, hint, alias_cache.get(make))
            if not floor:
                no_floor.append(key)
                continue
            if via != "chassis_code":
                floor = min(floor, PHANTOM_FLOOR)  # see PHANTOM_FLOOR

            deletions, insertions = [], []
            survivors = {y for years in variants.values() for y in years if y >= floor}
            for model, years in variants.items():
                below = sorted(y for y in years if y < floor)
                if not below:
                    continue
                keeps = years - set(below)
                deletions.extend((model, y) for y in below)
                if not keeps:
                    # Every row for this variant is below the floor. Copy the
                    # nameplate's surviving years if any sibling has some.
                    insertions.extend((model, y) for y in sorted(survivors))
            if deletions:
                plans[key] = {"floor": floor, "via": via,
                              "deletions": deletions, "insertions": insertions}

    tot_del = sum(len(v["deletions"]) for v in plans.values())
    tot_ins = sum(len(v["insertions"]) for v in plans.values())

    print("=" * 74)
    print("  OEM-FLOOR YEAR CLEANUP —", "EXECUTING" if args.execute else "DRY RUN")
    print("=" * 74)
    print(f"\nResidue nameplates considered : {len(residue)}")
    print(f"  with an oem_fitment floor   : {len(plans) + len([1 for k in residue if k not in plans and k not in no_floor])}")
    print(f"  no usable floor (untouched) : {len(no_floor)}")
    print(f"\nNameplates to change          : {len(plans)}")
    print(f"  rows to DELETE (below floor): {tot_del}")
    print(f"  rows to ADD (emptied trims) : {tot_ins}")
    print(f"  net change                  : {tot_ins - tot_del:+}\n")

    by_make = defaultdict(lambda: [0, 0, 0])
    for (make, _b), v in plans.items():
        by_make[make][0] += 1
        by_make[make][1] += len(v["deletions"])
        by_make[make][2] += len(v["insertions"])
    print(f"{'MAKE':<20} {'nameplates':>10} {'delete':>8} {'add':>6}")
    for make, (np_, d, i) in sorted(by_make.items(), key=lambda x: -x[1][1]):
        print(f"  {make:<18} {np_:>10} {d:>8} {i:>6}")

    print("\nSample (up to 20):")
    for (make, base), v in list(plans.items())[:20]:
        print(f"  {make:<10} {base:<28} floor={v['floor']} ({v['via']})  "
              f"-{len(v['deletions'])} +{len(v['insertions'])}")

    if not args.execute:
        print("\n[DRY RUN] No changes made. Re-run with --execute to apply.\n")
        return
    if not plans:
        print("\nNothing to change.\n")
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

    version_id = str(uuid.uuid4())
    deleted = inserted = 0
    with engine.begin() as conn:
        max_ver = conn.execute(
            text("SELECT COALESCE(MAX(version_number), 0) FROM vehicle_years_versions")).scalar() or 0
        conn.execute(text(
            "INSERT INTO vehicle_years_versions (id, version_number, committed_at, run_id,"
            " committed_count, updated_count, removed_count, conflict_count, committed_by,"
            " initiated_by, notes) VALUES (:id, :vn, :now, NULL, 0, 0, 0, 0, :by, :by, :notes)"
        ), {"id": version_id, "vn": max_ver + 1, "now": now, "by": SCRIPT_NAME,
            "notes": "OEM-floor cleanup — rows predating the oem_fitment year_from floor"})

        for (make, _base), v in plans.items():
            for model, year in v["deletions"]:
                row = conn.execute(text(
                    "SELECT engine_capacity, fuel, source FROM vehicle_years"
                    " WHERE make=:mk AND model=:md AND year=:yr"
                ), {"mk": make, "md": model, "yr": year}).fetchone()
                if row is None:
                    continue
                conn.execute(text(
                    "DELETE FROM vehicle_years WHERE make=:mk AND model=:md AND year=:yr"
                ), {"mk": make, "md": model, "yr": year})
                conn.execute(text(
                    "INSERT INTO vehicle_years_changelog (version_id, make, model, year,"
                    " change_type, old_values, new_values)"
                    " VALUES (:vid, :mk, :md, :yr, 'removed', :old, NULL)"
                ), {"vid": version_id, "mk": make, "md": model, "yr": year,
                    "old": json.dumps({"engine_capacity": row.engine_capacity,
                                       "fuel": row.fuel, "source": row.source})})
                deleted += 1

            for model, year in v["insertions"]:
                ec, fuel = specs.get((make, model), (None, None))
                res = conn.execute(text(
                    "INSERT INTO vehicle_years (make, model, year, engine_capacity, fuel, source)"
                    " VALUES (:mk, :md, :yr, :ec, :fuel, :src) ON CONFLICT DO NOTHING"
                ), {"mk": make, "md": model, "yr": year, "ec": ec, "fuel": fuel,
                    "src": SOURCE_TAG})
                if res.rowcount == 0:
                    continue
                conn.execute(text(
                    "INSERT INTO vehicle_years_changelog (version_id, make, model, year,"
                    " change_type, old_values, new_values)"
                    " VALUES (:vid, :mk, :md, :yr, 'added', NULL, :new)"
                ), {"vid": version_id, "mk": make, "md": model, "yr": year,
                    "new": json.dumps({"engine_capacity": ec, "fuel": fuel,
                                       "source": SOURCE_TAG})})
                inserted += 1

        conn.execute(text(
            "UPDATE vehicle_years_versions SET removed_count=:d, committed_count=:a"
            " WHERE id=:id"), {"d": deleted, "a": inserted, "id": version_id})

    print(f"\n  DONE")
    print(f"    Deleted: {deleted:,} rows")
    print(f"    Added:   {inserted:,} rows")
    print(f"    Version: {version_id} (revertible via the admin UI)\n")


if __name__ == "__main__":
    main()
