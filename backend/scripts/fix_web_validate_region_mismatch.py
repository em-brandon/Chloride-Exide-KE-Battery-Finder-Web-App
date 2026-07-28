"""
fix_web_validate_region_mismatch.py
------------------------------------
One-off cleanup for the DIN/NS region-resolution bug fixed in
pipelines/web_battery_validate.py's _resolve_battery_code() (it used to
trust a scraped "region" keyword hit over the vehicle's own make-based
region). Finds every web_battery_validation row whose battery_code region
doesn't match its make's region, and re-resolves battery_code using the
row's existing ah/technology (already correct — only the region-selection
step was wrong) via the now-fixed _resolve_battery_code().

Checks both directions: NS-make rows holding a DIN-coded battery_code
(the bug found in practice, ~490 rows as of 2026-07-28) and the symmetric
DIN-make-holding-NS-coded-battery case (queried clean, 0 rows, but checked
every run in case new data introduces it).

Usage
-----
    python scripts/fix_web_validate_region_mismatch.py             # dry-run
    python scripts/fix_web_validate_region_mismatch.py --execute   # apply changes

Takes a real backup (db_backup.create_backup()) immediately before
applying changes, logged to admin_backup_log with triggered_by set to
this script's name.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sqlalchemy import text

import db_backup
from db import engine
from matcher import _make_region, _battery_region
from models import AdminBackupLog
from pipelines.web_battery_validate import _resolve_battery_code


def _fetch_mismatched_rows(conn):
    rows = conn.execute(text(
        "SELECT id, make_n, model_n, year, battery_code, ah, technology"
        " FROM web_battery_validation WHERE battery_code IS NOT NULL"
    )).fetchall()

    mismatched = []
    for r in rows:
        make_region = _make_region(r.make_n)
        batt_region = _battery_region(r.battery_code)
        if make_region != batt_region:
            mismatched.append((r, make_region, batt_region))
    return mismatched


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-resolve battery_code for web_battery_validation rows whose region doesn't match their make."
    )
    parser.add_argument("--execute", action="store_true",
                         help="Apply changes. Without this flag only a dry-run is shown.")
    args = parser.parse_args()

    with engine.connect() as conn:
        mismatched = _fetch_mismatched_rows(conn)

    print("=" * 68)
    print("  FIX WEB-VALIDATE DIN/NS REGION MISMATCH —", "EXECUTING" if args.execute else "DRY RUN")
    print("=" * 68)

    ns_wrong  = [m for m in mismatched if m[1] == "NS"]
    din_wrong = [m for m in mismatched if m[1] == "DIN"]
    print(f"\nNS-make rows holding a DIN-coded battery_code : {len(ns_wrong):>5}")
    print(f"DIN-make rows holding an NS-coded battery_code: {len(din_wrong):>5}")
    print(f"Total mismatched rows                         : {len(mismatched):>5}\n")

    if not mismatched:
        print("Nothing to fix.\n")
        return

    print(f"{'ID':>8}  {'Make':<14}  {'Model':<25}  {'Year':>5}  {'Current battery_code':<28}  Region wrong-way")
    print("-" * 100)
    for r, make_region, batt_region in mismatched[:30]:
        print(f"{r.id:>8}  {r.make_n:<14}  {r.model_n:<25}  {r.year:>5}  {r.battery_code:<28}  make={make_region} batt={batt_region}")
    if len(mismatched) > 30:
        print(f"  ... and {len(mismatched) - 30} more rows not shown")

    if not args.execute:
        print(f"\n[DRY RUN] No changes made. Re-run with --execute to apply.\n")
        return

    print("\nTaking a backup before applying changes...")
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        try:
            result = db_backup.create_backup()
            conn.execute(text(
                "INSERT INTO admin_backup_log (filename, size_bytes, status, error_detail, triggered_by, created_at)"
                " VALUES (:f, :s, 'success', NULL, :t, :c)"
            ), {"f": result.filename, "s": result.size_bytes, "t": "fix_web_validate_region_mismatch.py", "c": now})
            print(f"  Backup created: {result.filename} ({result.size_bytes:,} bytes)")
        except db_backup.BackupError as exc:
            conn.execute(text(
                "INSERT INTO admin_backup_log (filename, size_bytes, status, error_detail, triggered_by, created_at)"
                " VALUES ('', NULL, 'failed', :e, :t, :c)"
            ), {"e": str(exc), "t": "fix_web_validate_region_mismatch.py", "c": now})
            print(f"\n  ERROR — backup failed, aborting cleanup:\n  {exc}\n")
            sys.exit(1)

    print("\nRe-resolving battery_code for mismatched rows...")
    updated = 0
    unchanged = 0
    failed = []
    with engine.begin() as conn:
        for r, _make_region_val, _batt_region_val in mismatched:
            resolved = _resolve_battery_code({"ah": r.ah, "technology": r.technology}, r.make_n)
            if resolved is None:
                failed.append(r)
                continue
            new_code, new_ah, new_tech = resolved
            if new_code == r.battery_code:
                unchanged += 1
                continue
            conn.execute(text(
                "UPDATE web_battery_validation SET battery_code = :bc, ah = :ah, technology = :tech WHERE id = :id"
            ), {"bc": new_code, "ah": new_ah, "tech": new_tech, "id": r.id})
            updated += 1

    print(f"\n  DONE")
    print(f"    Updated  : {updated:,} rows")
    print(f"    Unchanged: {unchanged:,} rows (re-resolved to the same code)")
    print(f"    Failed   : {len(failed):,} rows (no battery could be resolved)")
    if failed:
        print(f"    Failed row ids: {[r.id for r in failed]}")
    print()


if __name__ == "__main__":
    main()
