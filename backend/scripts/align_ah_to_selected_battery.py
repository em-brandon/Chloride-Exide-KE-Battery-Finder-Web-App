"""
align_ah_to_selected_battery.py
-------------------------------
Make web_battery_validation.ah equal the Ah of the battery its battery_code
actually names.

THE DEFECT
----------
5,453 live rows (25%) print an Ah that the battery beside it does not have —
"82Ah" next to an 80Ah battery code, "96Ah" next to a 95Ah one. Gaps are small
(mean ~3Ah, worst 15) because they are not wrong lookups: they are the
difference between a figure asked for and the size we actually stock.

Two independent sources produce it. Exide's fitment guide lists real
manufacturer figures (82, 96, 67) that are not sizes in our catalogue, and the
scraped web value is a free number too. Both then go through
_select_batteries(), which steps to the nearest stocked size — but the scripts
that wrote these rows kept the requested number in `ah` while storing the
selected battery's code.

WHY IT MATTERS FOR THE EXPORT
-----------------------------
This is the same shape as the defect the client already flagged in the OEM
Fitment Guide: two columns derived from one decision, disagreeing on the page.
`technology` was fixed by deriving it from the resolved battery; `ah` is the
last column still carrying the pre-resolution figure.

It changes no recommendation. matcher.py reads Ah out of battery_code, never
out of this column, so this only corrects what is printed.

fix_unchecked_ah_via_oem.py and (since this pass) fix_staging_ah_outliers.py
already store the selected battery's Ah, so new rows arrive correct; this is
the one-off backfill for rows written before that rule was settled.

Usage (run from backend/)
-------------------------
    python scripts/align_ah_to_selected_battery.py
    python scripts/align_ah_to_selected_battery.py --execute
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
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

SCRIPT = "align_ah_to_selected_battery.py"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--table", default="web_battery_validation")
    args = p.parse_args()

    with engine.connect() as conn:
        df = pd.read_sql(text(
            f"SELECT w.id, w.make_n, w.model_n, w.year, w.ah, b.ah AS spec_ah,"
            f" w.battery_code"
            f" FROM {args.table} w"
            f" JOIN battery_specs b ON b.battery_code = w.battery_code"
            f"  AND b.deleted_at IS NULL"
            f" WHERE w.ah IS NOT NULL AND w.ah <> b.ah"), conn)

    print(f"rows whose ah disagrees with their battery: {len(df):,}")
    if df.empty:
        print("  nothing to align\n")
        return 0

    df["gap"] = (df.ah - df.spec_ah).abs()
    per = Counter()
    for r in df.itertuples():
        per[str(r.make_n).upper()] += 1
    print(f"  makes affected : {len(per)}")
    print(f"  gap            : mean {df.gap.mean():.1f}Ah, worst {int(df.gap.max())}Ah")
    print("\n  by make:")
    for m, n in per.most_common(10):
        print(f"      {m:<16}{n:>6,}")
    print("\nexamples:")
    for r in df.head(8).itertuples():
        print(f"  {str(r.make_n).upper():<12}{str(r.model_n)[:30]:<31}{r.year}  "
              f"{int(r.ah):>3} -> {int(r.spec_ah):>3}Ah  ({r.battery_code})")

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

    vid = str(uuid.uuid4())
    rows = [{"id": int(r.id), "ah": int(r.spec_ah)} for r in df.itertuples()]
    log = [{"v": vid, "mk": str(r.make_n), "md": str(r.model_n), "yr": int(r.year),
            "o": f'{{"ah": {int(r.ah)}}}', "n": f'{{"ah": {int(r.spec_ah)}}}'}
           for r in df.itertuples()]

    with engine.begin() as c:
        ver = (c.execute(text("SELECT COALESCE(MAX(version_number),0)"
                              " FROM web_battery_validation_versions")).scalar() or 0) + 1
        c.execute(text(
            "INSERT INTO web_battery_validation_versions"
            " (id,version_number,committed_at,run_id,committed_count,removed_count,"
            "  conflict_count,notes,committed_by,initiated_by)"
            " VALUES (:i,:v,:a,:r,:cc,0,0,:n,:b,:b)"),
            {"i": vid, "v": ver, "a": now, "r": f"ah_align_{now:%Y%m%d_%H%M%S}",
             "cc": len(rows),
             "n": f"Align ah to the selected battery's rated Ah: {len(rows)} rows",
             "b": SCRIPT})
        for i in range(0, len(rows), 500):
            c.execute(text(f"UPDATE {args.table} SET ah=:ah, version_id='{vid}'"
                           f" WHERE id=:id"), rows[i:i + 500])
        for i in range(0, len(log), 500):
            c.execute(text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                " VALUES (:v,:mk,:md,:yr,'update',:o,:n)"), log[i:i + 500])

    print(f"  DONE — version {ver}, {len(rows):,} rows aligned\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
