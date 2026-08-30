"""
commit_web_battery_staging.py
-----------------------------
Promote web_battery_staging into the live web_battery_validation table, with a
backup, a version row and a full changelog so the commit stays revertible.

WHY THIS EXISTS AS A SCRIPT
---------------------------
The admin UI's commit path assumes a full-table pipeline run. This dataset is
being rebuilt a few makes at a time (Brave's prepaid search quota does not
allow one big run), so each batch needs the same promote-with-audit treatment
applied to a subset of makes. Doing that by hand produced versions 11 and 12;
this is the same steps, repeatable and reviewed.

REPLACE SEMANTICS
-----------------
By default every make present in staging is REPLACED in live: existing rows for
those makes that staging does not carry are deleted, not left behind. A rebuild
run covers the make's whole current year range, so a leftover row is by
definition one the run no longer believes in — usually a stale row from an
older run with years that the vehicle_years cleanup has since removed. Makes
absent from staging are never touched.

Pass --no-replace to upsert only, leaving unmatched live rows in place.

ORDER
-----
Run AFTER apply_oem_to_staging.py and fix_staging_ah_outliers.py, and only once
verify_web_validation_quality.py --table web_battery_staging reports READY.

Usage (run from backend/)
-------------------------
    python scripts/commit_web_battery_staging.py --label "renault_porsche_rebuild"
    python scripts/commit_web_battery_staging.py --label "..." --execute
"""

from __future__ import annotations

import argparse
import json
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

FIELDS = ("battery_code", "ah", "technology", "engine_cc", "fuel_type", "source")


def _vals(r) -> dict:
    out = {}
    for f in FIELDS:
        v = getattr(r, f, None)
        out[f] = None if v is None or (isinstance(v, float) and pd.isna(v)) else v
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", required=True,
                   help="Short run label, e.g. renault_porsche_rebuild.")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--no-replace", action="store_true",
                   help="Upsert only; do not delete live rows the run dropped.")
    args = p.parse_args()

    with engine.connect() as conn:
        st = pd.read_sql("SELECT * FROM web_battery_staging", conn)
        if st.empty:
            print("staging is empty — nothing to commit\n")
            return 1
        makes = sorted({str(m).upper().strip() for m in st.make_n})
        live = pd.read_sql(text(
            "SELECT * FROM web_battery_validation"
            " WHERE upper(trim(make_n)) = ANY(:mk)"), conn, params={"mk": makes})

    key = lambda r: (str(r.make_n).upper().strip(), str(r.model_n).upper().strip(),
                     int(r.year))
    live_by = {key(r): r for r in live.itertuples()}
    stage_keys = {key(r) for r in st.itertuples()}

    adds, updates, removes, unchanged = [], [], [], 0
    for r in st.itertuples():
        k = key(r)
        old = live_by.get(k)
        new = _vals(r)
        if old is None:
            adds.append((k, new, r))
        elif {f: _vals(old)[f] for f in FIELDS} == new:
            unchanged += 1
        else:
            updates.append((k, _vals(old), new, r, int(old.id)))
    if not args.no_replace:
        removes = [(k, _vals(v), int(v.id)) for k, v in live_by.items()
                   if k not in stage_keys]

    print(f"\nmakes in staging : {', '.join(makes)}")
    print(f"staging rows     : {len(st):,}")
    print(f"live rows (those makes): {len(live):,}\n")
    print(f"  add       {len(adds):>6,}")
    print(f"  update    {len(updates):>6,}")
    print(f"  remove    {len(removes):>6,}"
          + ("" if not args.no_replace else "   (--no-replace)"))
    print(f"  unchanged {unchanged:>6,}")

    per = Counter()
    for k, *_ in removes:
        per[k[0]] += 1
    if per:
        print("\n  removals by make:")
        for m, n in per.most_common():
            print(f"      {m:<16}{n:>6,}")

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
                {"f": res.filename, "s": res.size_bytes,
                 "t": "commit_web_battery_staging.py", "c": now})
        print(f"\n  backup: {res.filename}")
    except db_backup.BackupError as exc:
        print(f"\n  ERROR — backup failed, aborting: {exc}\n")
        return 1

    vid = str(uuid.uuid4())
    log: list[dict] = []
    with engine.begin() as c:
        ver = (c.execute(text("SELECT COALESCE(MAX(version_number),0)"
                              " FROM web_battery_validation_versions")).scalar() or 0) + 1
        c.execute(text(
            "INSERT INTO web_battery_validation_versions"
            " (id,version_number,committed_at,run_id,committed_count,removed_count,"
            "  conflict_count,notes,committed_by,initiated_by)"
            " VALUES (:i,:v,:a,:r,:cc,:rm,0,:n,:b,:b)"),
            {"i": vid, "v": ver, "a": now, "r": f"{args.label}_{now:%Y%m%d_%H%M%S}",
             "cc": len(adds) + len(updates), "rm": len(removes),
             "n": (f"{args.label}: {len(adds)} added, {len(updates)} updated, "
                   f"{len(removes)} removed across {', '.join(makes)}"),
             "b": args.label})

        for k, new, r in adds:
            c.execute(text(
                "INSERT INTO web_battery_validation"
                " (make_n,model_n,year,battery_code,ah,technology,source,validated_at,"
                "  engine_cc,fuel_type,run_id,version_id)"
                " VALUES (:mk,:md,:yr,:battery_code,:ah,:technology,:source,:at,"
                "  :engine_cc,:fuel_type,:rid,:vid)"),
                {"mk": r.make_n, "md": r.model_n, "yr": int(r.year), "at": now,
                 "rid": args.label, "vid": vid, **new})
            log.append({"v": vid, "mk": k[0], "md": k[1], "yr": k[2], "t": "add",
                        "o": None, "n": json.dumps(new, default=str)})

        for k, old, new, r, rid in updates:
            c.execute(text(
                "UPDATE web_battery_validation SET battery_code=:battery_code, ah=:ah,"
                " technology=:technology, engine_cc=:engine_cc, fuel_type=:fuel_type,"
                " source=:source, validated_at=:at, run_id=:rid, version_id=:vid"
                " WHERE id=:id"),
                {"id": rid, "at": now, "rid": args.label, "vid": vid, **new})
            log.append({"v": vid, "mk": k[0], "md": k[1], "yr": k[2], "t": "update",
                        "o": json.dumps(old, default=str),
                        "n": json.dumps(new, default=str)})

        if removes:
            ids = [rid for _, _, rid in removes]
            for i in range(0, len(ids), 500):
                c.execute(text("DELETE FROM web_battery_validation WHERE id = ANY(:ids)"),
                          {"ids": ids[i:i + 500]})
            for k, old, _ in removes:
                log.append({"v": vid, "mk": k[0], "md": k[1], "yr": k[2], "t": "remove",
                            "o": json.dumps(old, default=str), "n": None})

        for i in range(0, len(log), 500):
            c.execute(text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                " VALUES (:v,:mk,:md,:yr,:t,:o,:n)"), log[i:i + 500])

    print(f"  DONE — version {ver}: +{len(adds):,} / ~{len(updates):,} / "
          f"-{len(removes):,}, {len(log):,} changelog rows\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
