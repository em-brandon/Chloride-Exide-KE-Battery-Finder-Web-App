"""
quarantine_unverifiable_years.py
--------------------------------
Move vehicle_years rows for nameplates nobody could date into the
vehicle_years_unverifiable table, so the live matcher only serves years
something actually vouches for, and the moved rows become an explicit
manual-research worklist rather than silent bad data.

WHY THIS ISN'T SIMPLY "MOVE EVERYTHING ja.wikipedia MISSED"
-----------------------------------------------------------
ja.wikipedia failing to resolve a nameplate says nothing about whether the
stored years are wrong — it documents JDM passenger cars far better than
commercial vehicles or Western marques, so a miss is usually a gap in the
source, not evidence against our data. Moving every unresolved nameplate was
measured against the live table and would have removed 13,403 rows (73% of
all Japanese-make rows), effectively emptying Hino (98.9%), Isuzu (98.5%),
Nissan Diesel/UD (100%) and Mitsubishi Fuso (100%) — makes whose customers
would then get no battery recommendation at all.

So each unresolved nameplate is triaged on the evidence that IS available:

  corroboration  an independent year source already in this database
                 (oem_fitment — Exide's own global fitment guide;
                 fueleconomy_vehicles — US EPA; web_battery_validation)
                 holding a year range for the same make/nameplate that
                 overlaps what we store.

  red flags      fingerprints of the specific bugs that put bad years here:
                 a start year below YEAR_FLOOR, a span longer than
                 MAX_PLAUSIBLE_SPAN, an end pinned to the current year, and
                 powertrain anachronisms (a "HYBRID" trim dated before 1997).
                 Anachronisms matter because corroboration matches at
                 nameplate level ("ALTO%") and will happily confirm an
                 "ALTO HYBRID" dated 1994 using the plain Alto's real 1994
                 start — the exact trim-vs-nameplate granularity error this
                 whole effort exists to fix.

Only nameplates with red flags are quarantined by default. Corroborated and
clean-looking ones stay put: unverified is not the same as wrong, and
removing a model from the dropdown is a worse customer outcome than serving
a year range that merely lacks a citation.

CAVEAT: these are heuristics, not proof. Corroboration is nameplate-level, so
a trim-specific error can still pass (TOYOTA YARIS HYBRID dated from 1999
survives because the plain Yaris really does start then). Treat the kept
groups as "no evidence against", not "verified".

Usage (run from backend/)
-------------------------
    python scripts/quarantine_unverifiable_years.py                  # dry run, suspect only
    python scripts/quarantine_unverifiable_years.py --group all      # dry run, every unresolved nameplate
    python scripts/quarantine_unverifiable_years.py --execute        # apply
    python scripts/quarantine_unverifiable_years.py --restore BATCH  # undo one batch

Reads the residue list from the dry-run/exec logs written by
fix_vehicle_years_phantom_dates.py (--residue-dir), so it quarantines exactly
what that pass reported and never re-queries ja.wikipedia.

Takes a real backup before applying, and writes vehicle_years_versions /
vehicle_years_changelog entries ('removed', with full old_values) so the move
is revertible through the admin UI like any other pipeline change — on top of
the row copies held in vehicle_years_unverifiable itself.
"""

from __future__ import annotations

import argparse
import glob
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

SCRIPT_NAME = "quarantine_unverifiable_years.py"

YEAR_FLOOR = 1990
MAX_PLAUSIBLE_SPAN = 25
CURRENT_YEAR = datetime.now(timezone.utc).year

# Badge/powertrain words that postdate a known year — see module docstring.
ANACHRONISMS = {
    "HYBRID": 1997, "E:HEV": 2018, "PHEV": 2010, "PHV": 2012,
    "EV": 2009, "E-POWER": 2016, "TFSI": 2004, "TSI": 2005,
    "SKYACTIV": 2011, "BLUETEC": 2006,
}

_RESIDUE_RE = re.compile(
    r"\[\d+/\d+\]\s+(?P<nameplate>.+?)\s+\.\.\.\s+UNCONFIRMED\s+\((?P<reason>[a-z_]+)")


def _log_make(path):
    """Recover the make from a per-make log filename (TOYOTA.log, NISSAN_DIESEL_UD.log)."""
    stem = os.path.basename(path)[:-4]
    return stem.replace("_DIESEL_UD", " DIESEL/UD").replace("_FUSO", " FUSO").replace("_", " ")


def load_residue(residue_dir):
    """{(make, base_model): reason} from fix_vehicle_years_phantom_dates.py logs."""
    residue = {}
    for path in glob.glob(os.path.join(residue_dir, "*.log")):
        make = _log_make(path)
        with open(path, "rb") as fh:
            # Logs may be UTF-16 if produced through a PowerShell redirect.
            txt = fh.read().replace(b"\x00", b"").decode("utf-8", errors="replace")
        for m in _RESIDUE_RE.finditer(txt):
            full = m.group("nameplate").strip()
            base = full[len(make):].strip() if full.upper().startswith(make.upper()) else full
            residue[(make, base)] = m.group("reason")
    return residue


def anachronism_flag(base_model, year_from):
    tokens = set(re.findall(r"[A-Z:\-]+", base_model.upper()))
    for word, earliest in ANACHRONISMS.items():
        if word in tokens and year_from < earliest:
            return f"{word}-before-{earliest}"
    return None


def corroborating_source(conn, make, base):
    """
    First INDEPENDENT source holding a usable year range for this nameplate.

    web_battery_validation is deliberately not consulted. It is populated by
    running the web-validation pipeline over vehicle_years rows, so its years
    are derived from the very data being audited — it would vouch for the
    phantom years with the phantom years. Observed live: it "confirmed" HINO
    MELPHA as 1953-2026 and DAIHATSU ATRAI as 1960-2020, both echoes of the
    bug rather than evidence against it.

    oem_fitment (Exide's own fitment guide) and fueleconomy_vehicles (US EPA)
    are both loaded from outside sources and are genuinely independent.
    """
    head = base.split()[0] if base.split() else base
    like = head + "%"
    for sql, params, name in (
        ("SELECT min(year_from), max(year_to) FROM oem_fitment"
         " WHERE upper(make)=upper(:mk) AND upper(model) LIKE upper(:lk)"
         "   AND year_from BETWEEN 1950 AND :cy",
         {"mk": make, "lk": like, "cy": CURRENT_YEAR}, "oem_fitment"),
        ("SELECT min(year), max(year) FROM fueleconomy_vehicles"
         " WHERE upper(make)=upper(:mk) AND upper(model) LIKE upper(:lk)",
         {"mk": make, "lk": like}, "fueleconomy"),
    ):
        row = conn.execute(text(sql), params).fetchone()
        if row and row[0]:
            return name, row[0], row[1] or CURRENT_YEAR
    return None


def triage(conn, residue):
    """Classify each residue nameplate. Returns {(make, base): (group, reason, flags)}."""
    stored = defaultdict(set)
    for r in conn.execute(text("SELECT make, model, year FROM vehicle_years")).fetchall():
        stored[(r.make, extract_base_model(r.make, r.model))].add(r.year)

    out = {}
    for (make, base), reason in residue.items():
        years = stored.get((make, base))
        if not years:
            continue
        lo, hi = min(years), max(years)
        span = hi - lo + 1
        flags = []
        if lo < YEAR_FLOOR:
            flags.append(f"starts-{lo}")
        if span > MAX_PLAUSIBLE_SPAN:
            flags.append(f"spans-{span}y")
        if hi >= CURRENT_YEAR and span > MAX_PLAUSIBLE_SPAN:
            flags.append("open-ended")
        anach = anachronism_flag(base, lo)
        if anach:
            flags.append(anach)

        corr = corroborating_source(conn, make, base)
        overlaps = bool(corr) and not (hi < corr[1] or lo > corr[2])

        if flags:
            group = "suspect"
        elif corr and overlaps:
            group = "corroborated"
        else:
            group = "plausible"
        out[(make, base)] = (group, reason, ",".join(flags) or "-")
    return out


def collect_rows(conn, targets):
    """Every vehicle_years row belonging to the target nameplates."""
    rows = []
    for r in conn.execute(text(
        "SELECT id, make, model, year, engine_capacity, fuel, source, model_number"
        " FROM vehicle_years")).fetchall():
        key = (r.make, extract_base_model(r.make, r.model))
        if key in targets:
            rows.append((r, key))
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true", help="Apply. Without this, dry run only.")
    p.add_argument("--group", choices=["suspect", "all"], default="suspect",
                   help="'suspect' (default) quarantines only red-flagged nameplates; "
                        "'all' quarantines every unresolved nameplate.")
    p.add_argument("--residue-dir", default=None,
                   help="Directory of fix_vehicle_years_phantom_dates.py logs to read the "
                        "residue list from.")
    p.add_argument("--restore", metavar="BATCH_ID",
                   help="Move a previously quarantined batch back into vehicle_years.")
    args = p.parse_args()

    if args.restore:
        return restore_batch(args.restore, args.execute)

    if not args.residue_dir:
        p.error("--residue-dir is required (directory of per-make cleanup logs)")

    residue = load_residue(args.residue_dir)
    if not residue:
        print(f"No residue entries found in {args.residue_dir}")
        return

    with engine.connect() as conn:
        classified = triage(conn, residue)
        wanted = {"suspect"} if args.group == "suspect" else {"suspect", "corroborated", "plausible"}
        targets = {k: v for k, v in classified.items() if v[0] in wanted}
        rows = collect_rows(conn, targets)

    print("=" * 74)
    print("  QUARANTINE UNVERIFIABLE YEARS —", "EXECUTING" if args.execute else "DRY RUN")
    print("=" * 74)
    counts = defaultdict(int)
    for group, _reason, _flags in classified.values():
        counts[group] += 1
    print(f"\nResidue nameplates read : {len(residue)}")
    print(f"  suspect (red flags)   : {counts['suspect']}")
    print(f"  corroborated          : {counts['corroborated']}")
    print(f"  plausible, no evidence: {counts['plausible']}")
    print(f"\nSelected (--group {args.group}): {len(targets)} nameplates, {len(rows)} rows\n")

    by_make = defaultdict(lambda: [0, 0])
    for _r, key in rows:
        by_make[key[0]][1] += 1
    for key in targets:
        by_make[key[0]][0] += 1
    print(f"{'MAKE':<20} {'nameplates':>10} {'rows':>7}")
    for make, (np_, nrows) in sorted(by_make.items(), key=lambda x: -x[1][1]):
        print(f"  {make:<18} {np_:>10} {nrows:>7}")

    if not args.execute:
        print("\n[DRY RUN] Nothing moved. Re-run with --execute to apply.\n")
        return
    if not rows:
        print("\nNothing to quarantine.\n")
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
        max_ver = conn.execute(
            text("SELECT COALESCE(MAX(version_number), 0) FROM vehicle_years_versions")
        ).scalar() or 0
        conn.execute(text(
            "INSERT INTO vehicle_years_versions (id, version_number, committed_at, run_id,"
            " committed_count, updated_count, removed_count, conflict_count, committed_by,"
            " initiated_by, notes) VALUES (:id, :vn, :now, :batch, 0, 0, 0, 0, :by, :by, :notes)"
        ), {"id": version_id, "vn": max_ver + 1, "now": now, "batch": batch_id,
            "by": SCRIPT_NAME,
            "notes": f"Quarantined unverifiable nameplates (--group {args.group}) "
                     f"to vehicle_years_unverifiable, batch {batch_id}"})

        for r, key in rows:
            group, reason, flags = targets[key]
            conn.execute(text(
                "INSERT INTO vehicle_years_unverifiable (make, model, year, engine_capacity,"
                " fuel, source, model_number, base_model, reason, moved_at, batch_id)"
                " VALUES (:make, :model, :year, :ec, :fuel, :src, :mn, :base, :reason, :now, :batch)"
                " ON CONFLICT DO NOTHING"
            ), {"make": r.make, "model": r.model, "year": r.year, "ec": r.engine_capacity,
                "fuel": r.fuel, "src": r.source, "mn": r.model_number, "base": key[1],
                "reason": f"{reason}|{flags}", "now": now, "batch": batch_id})
            conn.execute(text("DELETE FROM vehicle_years WHERE id = :id"), {"id": r.id})
            conn.execute(text(
                "INSERT INTO vehicle_years_changelog (version_id, make, model, year,"
                " change_type, old_values, new_values)"
                " VALUES (:vid, :make, :model, :year, 'removed', :old, NULL)"
            ), {"vid": version_id, "make": r.make, "model": r.model, "year": r.year,
                "old": json.dumps({"engine_capacity": r.engine_capacity, "fuel": r.fuel,
                                   "source": r.source})})
            moved += 1

        conn.execute(text("UPDATE vehicle_years_versions SET removed_count = :n WHERE id = :id"),
                     {"n": moved, "id": version_id})

    print(f"\n  DONE")
    print(f"    Moved:    {moved:,} rows -> vehicle_years_unverifiable")
    print(f"    Batch ID: {batch_id}")
    print(f"    Version:  {version_id} (revertible via the admin UI)")
    print(f"\n  To undo: python scripts/quarantine_unverifiable_years.py "
          f"--restore {batch_id} --execute\n")


def restore_batch(batch_id, execute):
    """Move a quarantined batch back into vehicle_years."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT make, model, year, engine_capacity, fuel, source, model_number"
            " FROM vehicle_years_unverifiable WHERE batch_id = :b"), {"b": batch_id}).fetchall()
    print(f"Batch {batch_id}: {len(rows)} rows")
    if not execute:
        print("[DRY RUN] Re-run with --execute to restore.\n")
        return
    with engine.begin() as conn:
        for r in rows:
            conn.execute(text(
                "INSERT INTO vehicle_years (make, model, year, engine_capacity, fuel, source,"
                " model_number) VALUES (:make, :model, :year, :ec, :fuel, :src, :mn)"
                " ON CONFLICT DO NOTHING"
            ), {"make": r.make, "model": r.model, "year": r.year, "ec": r.engine_capacity,
                "fuel": r.fuel, "src": r.source, "mn": r.model_number})
        conn.execute(text("DELETE FROM vehicle_years_unverifiable WHERE batch_id = :b"),
                     {"b": batch_id})
    print(f"Restored {len(rows)} rows to vehicle_years.\n")


if __name__ == "__main__":
    main()
