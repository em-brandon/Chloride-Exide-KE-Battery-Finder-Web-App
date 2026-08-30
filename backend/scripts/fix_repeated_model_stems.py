"""
fix_repeated_model_stems.py
---------------------------
Repair model names that repeat their own leading tokens.

THE DEFECT
----------
470 vehicle_years rows across 52 models carry a name whose stem is duplicated,
because a trim string was concatenated onto a model name that already contained
it:

    BMW      M3 M3 50TH ANNIVERSARY LIMITED   ->  M3 50TH ANNIVERSARY LIMITED
    PORSCHE  718 BOXSTER 718 BOXSTER S        ->  718 BOXSTER S
    JAGUAR   XF SPORTBRAKE XF SPORTBRAKE R    ->  XF SPORTBRAKE R

They reach the exported fitment guide verbatim, where they read as a broken
export, and they split one vehicle across two dropdown entries in the app.

THREE CASES, ONLY TWO OF THEM SAFE
----------------------------------
Stripping the repeat is not simply a rename, because the correctly-named row
often already exists:

  * 292 rows  — no row exists under the repaired name. Rename in place.
  * 162 rows  — a row exists under the repaired name AND matches on engine
                capacity and fuel. Same vehicle listed twice; drop the
                malformed copy.
  *  16 rows  — a row exists under the repaired name but DIFFERS. Porsche
                "911 911 TURBO" is 3800 cc while "911 TURBO" is 3700 cc: two
                real engine variants that happen to collapse to one name.
                LEFT UNTOUCHED — merging them would silently delete a variant,
                and a slightly ugly name is much cheaper than a missing car.

web_battery_validation is keyed on the model name too, so it is carried along
in the same transaction: renamed where its own key is free, dropped where the
repaired name is already present there.

Usage (run from backend/)
-------------------------
    python scripts/fix_repeated_model_stems.py
    python scripts/fix_repeated_model_stems.py --execute
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
from matcher import _norm_model_key

SCRIPT = "fix_repeated_model_stems.py"


def strip_repeat(model: str):
    """'718 BOXSTER 718 BOXSTER S' -> '718 BOXSTER S'; None if no repeat.

    Tokenises the matcher's canonical form, not the raw string. The two tables
    spell the same defect differently — vehicle_years holds "GLB GLB180" while
    web_battery_validation holds "GLB GLB 180" — so a raw split() sees a repeat
    in one and not the other, strips only that one, and leaves 71 validation
    rows pointing at a vehicle that no longer exists under that name. Splitting
    on _norm_model_key makes both read as [GLB, GLB, 180] and collapse
    identically, which is also the form the ghost check compares on.
    """
    t = _norm_model_key(str(model)).split()
    # Longest repeated prefix first, so a doubly-repeated stem collapses fully.
    for n in range(len(t) // 2, 0, -1):
        if t[:n] == t[n:2 * n]:
            return " ".join(t[n:])
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--drop-on-conflict", action="store_true",
                   help="Delete the repeated-name row even when the correctly "
                        "named twin has different specs.")
    args = p.parse_args()

    # --drop-on-conflict resolves the third case the other way.
    #
    # The conservative default keeps "911 911 TURBO" (3800 cc) alongside
    # "911 TURBO" (3700 cc) on the grounds that they might be two real engine
    # variants. They are not: Porsche has never sold a model called "911 911
    # Turbo". The name is an artifact in every case, so the differing capacity
    # is a second symptom of the same bad record rather than evidence of a
    # distinct car, and keeping the row publishes a model that does not exist.
    # Renaming it is impossible — the correct name is already taken at the same
    # years — so the row is quarantined like any other bad record.

    with engine.connect() as conn:
        vy = pd.read_sql(
            "SELECT id, make, model, year, engine_capacity, fuel FROM vehicle_years",
            conn)
        wv = pd.read_sql(
            "SELECT id, make_n, model_n, year FROM web_battery_validation", conn)

    def k(mk, md, yr):
        return (str(mk).upper().strip(), str(md).upper().strip(), int(yr))

    vy_by = {k(r.make, r.model, r.year): r for r in vy.itertuples()}
    wv_by = {k(r.make_n, r.model_n, r.year): r for r in wv.itertuples()}

    vy_rename, vy_drop, skipped = [], [], []
    for r in vy.itertuples():
        new = strip_repeat(r.model)
        if new is None:
            continue
        twin = vy_by.get(k(r.make, new, r.year))
        if twin is None:
            vy_rename.append((r, new))
        elif (str(twin.engine_capacity) == str(r.engine_capacity)
              and str(twin.fuel) == str(r.fuel)) or args.drop_on_conflict:
            vy_drop.append((r, new))
        else:
            skipped.append((r, new))

    wv_rename, wv_drop = [], []
    for r in wv.itertuples():
        new = strip_repeat(r.model_n)
        if new is None:
            continue
        # Mirror whatever vehicle_years decided: if the pair was left alone
        # there, leaving it here keeps the two tables agreeing.
        if any(k(s.make, s.model, s.year) == k(r.make_n, r.model_n, r.year)
               for s, _ in skipped):
            continue
        if k(r.make_n, new, r.year) in wv_by:
            wv_drop.append((r, new))
        else:
            wv_rename.append((r, new))

    print(f"vehicle_years")
    print(f"  rename (no clash)          : {len(vy_rename):>5,}")
    print(f"  drop duplicate (identical) : {len(vy_drop):>5,}")
    print(f"  left alone (real variants) : {len(skipped):>5,}")
    print(f"web_battery_validation")
    print(f"  rename                     : {len(wv_rename):>5,}")
    print(f"  drop duplicate             : {len(wv_drop):>5,}")

    seen, ex = set(), []
    for r, new in vy_rename + vy_drop:
        if r.model in seen:
            continue
        seen.add(r.model)
        if len(ex) < 10:
            ex.append(f"  {str(r.make):<10}{str(r.model)[:40]:<41} -> {new}")
    print("\nexamples:")
    for e in ex:
        print(e)
    if skipped:
        print("\nleft alone (differing specs):")
        for r, new in skipped[:4]:
            print(f"  {str(r.make):<10}{str(r.model)[:36]:<37} {r.engine_capacity}cc"
                  f"  vs existing {new}")

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
            " VALUES (:i,:v,:a,:r,:cc,:rm,0,:n,:b,:b)"),
            {"i": vid, "v": ver, "a": now, "r": f"model_stem_{now:%Y%m%d_%H%M%S}",
             "cc": len(wv_rename), "rm": len(wv_drop),
             "n": (f"Repeated model stems: {len(wv_rename)} renamed, "
                   f"{len(wv_drop)} duplicates dropped"),
             "b": SCRIPT})

        log = []
        for r, new in wv_rename:
            c.execute(text("UPDATE web_battery_validation SET model_n=:m,"
                           " version_id=:v WHERE id=:i"),
                      {"m": new, "v": vid, "i": int(r.id)})
            log.append({"v": vid, "mk": r.make_n, "md": r.model_n, "yr": int(r.year),
                        "t": "update", "o": json.dumps({"model_n": r.model_n}),
                        "n": json.dumps({"model_n": new})})
        for r, _ in wv_drop:
            log.append({"v": vid, "mk": r.make_n, "md": r.model_n, "yr": int(r.year),
                        "t": "remove", "o": json.dumps({"model_n": r.model_n}),
                        "n": None})
        if wv_drop:
            ids = [int(r.id) for r, _ in wv_drop]
            for i in range(0, len(ids), 500):
                c.execute(text("DELETE FROM web_battery_validation"
                               " WHERE id = ANY(:ids)"), {"ids": ids[i:i + 500]})
        for i in range(0, len(log), 500):
            c.execute(text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                " VALUES (:v,:mk,:md,:yr,:t,:o,:n)"), log[i:i + 500])

        for r, new in vy_rename:
            c.execute(text("UPDATE vehicle_years SET model=:m WHERE id=:i"),
                      {"m": new, "i": int(r.id)})
        if vy_drop:
            ids = [int(r.id) for r, _ in vy_drop]
            for i in range(0, len(ids), 500):
                c.execute(text("DELETE FROM vehicle_years WHERE id = ANY(:ids)"),
                          {"ids": ids[i:i + 500]})

    print(f"  DONE — version {ver}: vehicle_years {len(vy_rename)} renamed / "
          f"{len(vy_drop)} dropped; validation {len(wv_rename)} renamed / "
          f"{len(wv_drop)} dropped\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
