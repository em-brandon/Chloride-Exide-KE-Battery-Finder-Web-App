"""
merge_mercedes_make_split.py
----------------------------
Collapse the MERCEDES / MERCEDES-BENZ make split onto a single name.

WHY
---
CRSP carries the same manufacturer under two spellings, so the dataset lists
Mercedes twice — 1,330 rows as MERCEDES and 12 as MERCEDES-BENZ in
vehicle_years, mirrored into web_battery_validation. Consequences:

  * The exported fitment guide shows two Mercedes makes, one of them nearly
    empty, which reads as missing data to anyone reviewing it.
  * The make dropdown offers both, and a shopper choosing the 12-row spelling
    sees almost no models.
  * Every make-keyed rule has to spell it twice to stay correct (_LUXURY_MAKES
    and _LUXURY_AGM_FROM both carry duplicate entries today), and any rule that
    forgets the second spelling silently misses those rows.

MERCEDES is the surviving name: it holds 99% of the rows, and the alternative
would rewrite far more data for no gain.

SAFETY
------
Both tables are keyed unique on (make, model, year), so a merge could collide.
Verified zero collisions in both before writing — the 12 rows are a single
model that does not appear under the MERCEDES spelling at any year. The script
re-checks this at run time and aborts rather than dropping a row, because a
later pipeline run could introduce an overlap that did not exist when this was
written.

Usage (run from backend/)
-------------------------
    python scripts/merge_mercedes_make_split.py
    python scripts/merge_mercedes_make_split.py --execute
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
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

OLD, NEW = "MERCEDES-BENZ", "MERCEDES"
SCRIPT = "merge_mercedes_make_split.py"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    with engine.connect() as conn:
        vy = pd.read_sql(text(
            "SELECT id, model, year FROM vehicle_years"
            " WHERE upper(trim(make)) = :o"), conn, params={"o": OLD})
        wv = pd.read_sql(text(
            "SELECT id, model_n, year FROM web_battery_validation"
            " WHERE upper(trim(make_n)) = :o"), conn, params={"o": OLD})
        vy_clash = conn.execute(text(
            "SELECT count(*) FROM vehicle_years a JOIN vehicle_years b"
            "  ON upper(trim(a.model)) = upper(trim(b.model)) AND a.year = b.year"
            " WHERE upper(trim(a.make)) = :o AND upper(trim(b.make)) = :n"),
            {"o": OLD, "n": NEW}).scalar()
        wv_clash = conn.execute(text(
            "SELECT count(*) FROM web_battery_validation a"
            " JOIN web_battery_validation b"
            "  ON a.model_n = b.model_n AND a.year = b.year"
            " WHERE upper(trim(a.make_n)) = :o AND upper(trim(b.make_n)) = :n"),
            {"o": OLD, "n": NEW}).scalar()

    print(f"{OLD} -> {NEW}")
    print(f"  vehicle_years          : {len(vy):>5,} rows"
          f"   ({vy.model.nunique()} model(s))")
    print(f"  web_battery_validation : {len(wv):>5,} rows")
    print(f"  collisions             : vehicle_years {vy_clash}, "
          f"web_battery_validation {wv_clash}")
    if not len(vy) and not len(wv):
        print("\n  nothing to merge — already collapsed\n")
        return 0
    if vy_clash or wv_clash:
        print("\n  ABORT — merging would collide with an existing row and drop"
              " data. Resolve the duplicate keys first.\n")
        return 1

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
    with engine.begin() as c:
        ver = (c.execute(text("SELECT COALESCE(MAX(version_number),0)"
                              " FROM web_battery_validation_versions")).scalar() or 0) + 1
        c.execute(text(
            "INSERT INTO web_battery_validation_versions"
            " (id,version_number,committed_at,run_id,committed_count,removed_count,"
            "  conflict_count,notes,committed_by,initiated_by)"
            " VALUES (:i,:v,:a,:r,:cc,0,0,:n,:b,:b)"),
            {"i": vid, "v": ver, "a": now, "r": f"merc_merge_{now:%Y%m%d_%H%M%S}",
             "cc": len(wv), "n": f"Merged {OLD} into {NEW}: {len(wv)} rows",
             "b": SCRIPT})
        if len(wv):
            log = [{"v": vid, "mk": OLD, "md": r.model_n, "yr": int(r.year),
                    "o": json.dumps({"make_n": OLD}),
                    "n": json.dumps({"make_n": NEW})} for r in wv.itertuples()]
            c.execute(text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                " VALUES (:v,:mk,:md,:yr,'update',:o,:n)"), log)
            c.execute(text(
                "UPDATE web_battery_validation SET make_n = :n, version_id = :vid"
                " WHERE upper(trim(make_n)) = :o"),
                {"n": NEW, "o": OLD, "vid": vid})
        c.execute(text("UPDATE vehicle_years SET make = :n"
                       " WHERE upper(trim(make)) = :o"), {"n": NEW, "o": OLD})

    print(f"  DONE — version {ver}: {len(wv)} validation rows and "
          f"{len(vy)} vehicle_years rows merged\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
