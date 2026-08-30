"""
fix_premium_agm_year_gate.py
----------------------------
Re-derive technology + battery_code for premium-make rows dated before AGM was
an OEM fitment.

WHY
---
_preferred_tech() returned AGM for any make in _LUXURY_MAKES with no reference
to the model year, so a 2001 BMW 320i and a 2003 Land Rover Discovery were both
recommended AGM. AGM only reached premium production cars alongside stop-start
and brake-energy regeneration (BMW ~2007, Mercedes ~2008); before that these
cars shipped with flooded batteries. The rule was reasoning about the brand
rather than the technology's timeline.

matcher.py now gates that branch on _LUXURY_AGM_FROM_YEAR (see _luxury_agm),
which fixes the live app. This script applies the same correction to the rows
already stored in web_battery_validation so the exported fitment guide agrees
with what the app now recommends — otherwise the guide keeps quoting AGM for
cars the app has stopped recommending it for.

The Ah is deliberately preserved: only the technology was wrong, and the
battery_code is re-selected at the same capacity in the corrected technology.

Usage (run from backend/)
-------------------------
    python scripts/fix_premium_agm_year_gate.py
    python scripts/fix_premium_agm_year_gate.py --execute
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
from matcher import (_LUXURY_AGM_FROM, _LUXURY_AGM_FROM_YEAR, _LUXURY_MAKES,
                     _infer_stop_start, _make_region, _norm_fuel,
                     _preferred_tech, _select_batteries)

SCRIPT = "fix_premium_agm_year_gate.py"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--table", default="web_battery_validation")
    args = p.parse_args()

    makes = sorted(_LUXURY_MAKES)
    # Each make has its own cutoff, so scan up to the LATEST of them and let
    # _preferred_tech apply the per-make date per row. Bounding the query by a
    # single year would silently skip the late adopters (Maserati 2013) whose
    # rows are exactly the ones the per-make table exists to correct.
    cutoff = max([*_LUXURY_AGM_FROM.values(), _LUXURY_AGM_FROM_YEAR])
    with engine.connect() as conn:
        df = pd.read_sql(text(
            f"SELECT id, make_n, model_n, year, ah, technology, battery_code,"
            f" engine_cc, fuel_type FROM {args.table}"
            f" WHERE upper(trim(make_n)) = ANY(:mk) AND year < :y"
            f"   AND ah IS NOT NULL"), conn,
            params={"mk": makes, "y": cutoff})

    print(f"premium rows before {cutoff} (latest per-make cutoff): {len(df):,}")
    if df.empty:
        print("  nothing to correct\n")
        return 0
    df["engine_cc"] = pd.to_numeric(df.engine_cc, errors="coerce")

    updates, moves, examples = [], Counter(), []
    for r in df.itertuples():
        mk = str(r.make_n).upper().strip()
        cc = int(r.engine_cc) if pd.notna(r.engine_cc) else 0
        nf = _norm_fuel(r.fuel_type) if r.fuel_type else ""
        # A row already stored as AGM on a pre-gate year is anachronistic by
        # definition, so ask for MF outright instead of routing through
        # _preferred_tech. Going through the normal preference re-reads
        # fuel_type, and where that column is wrong (HYBRID on a 2004 diesel
        # X3) it prefers EFB, finds none stocked at that Ah, and falls back to
        # AGM — leaving the anachronism in place. Asking for MF directly
        # sidesteps a column we know is unreliable on exactly these rows.
        # _select_batteries still returns AGM when nothing else is stocked at
        # that capacity, which the downgrade check below then declines.
        anachronistic_agm = str(r.technology).upper() == "AGM"
        try:
            if anachronistic_agm:
                pref = "MF"
            else:
                pref = _preferred_tech(cc, nf, int(r.year), mk,
                                       _infer_stop_start(mk, int(r.year), nf))
            primary, _ = _select_batteries(int(r.ah), pref, _make_region(mk))
        except Exception:
            moves["resolve_failed"] += 1
            continue
        old_tech = str(r.technology).upper()
        new_tech = str(primary["technology"]).upper()
        if primary["battery_code"] == r.battery_code and new_tech == old_tech:
            continue

        # STRIP ANACHRONISTIC AGM ONLY — never upgrade a row here.
        #
        # Re-deriving technology wholesale means trusting engine_cc and
        # fuel_type, and on exactly these rows both are unreliable: the 2006
        # BMW X3 block carries engine_cc 0 with fuel_type PETROL on a "20 D"
        # diesel, HYBRID on another diesel, and EV on an "X3 M Competition"
        # that did not exist until 2019. A HYBRID mislabel prefers EFB, nothing
        # EFB is stocked at 80Ah, and the fallback lands on AGM — so a data
        # error silently becomes an AGM upgrade on a 2006 car, the precise
        # outcome this gate exists to prevent.
        #
        # The gate's job is narrow: remove AGM the model year cannot justify.
        # Anything else is a vehicle-data problem to fix at the source.
        if old_tech != "AGM" or new_tech == "AGM":
            moves["skipped_not_a_downgrade"] += 1
            continue
        moves[f"{str(r.technology).upper()} -> {str(primary['technology']).upper()}"] += 1
        updates.append({"id": int(r.id), "battery_code": primary["battery_code"],
                        "technology": primary["technology"], "ah": int(primary["ah"]),
                        "_old": {"battery_code": r.battery_code,
                                 "technology": r.technology, "ah": int(r.ah)},
                        "_key": (mk, str(r.model_n), int(r.year))})
        if len(examples) < 10:
            examples.append(f"  {mk:<11}{str(r.model_n)[:30]:<31}{r.year}  "
                            f"{str(r.technology):<4} -> {primary['technology']:<4}  "
                            f"{r.battery_code} -> {primary['battery_code']}")

    print(f"  rows to correct : {len(updates):,}")
    for k, n in moves.most_common():
        print(f"      {k:<22}{n:>6,}")
    if examples:
        print("\nexamples:")
        for e in examples:
            print(e)

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
            {"i": vid, "v": ver, "a": now, "r": f"agm_year_gate_{now:%Y%m%d_%H%M%S}",
             "cc": len(updates),
             "n": (f"Premium AGM per-make year gate (<{cutoff}): "
                   f"{len(updates)} rows re-derived"),
             "b": SCRIPT})
        rows = [{k: v for k, v in u.items() if not k.startswith("_")} for u in updates]
        for i in range(0, len(rows), 500):
            c.execute(text(
                f"UPDATE {args.table} SET battery_code=:battery_code,"
                f" technology=:technology, ah=:ah, version_id='{vid}' WHERE id=:id"),
                rows[i:i + 500])
        log = [{"v": vid, "mk": u["_key"][0], "md": u["_key"][1], "yr": u["_key"][2],
                "o": json.dumps(u["_old"], default=str),
                "n": json.dumps({k: v for k, v in u.items()
                                 if k in ("battery_code", "technology", "ah")},
                                default=str)} for u in updates]
        for i in range(0, len(log), 500):
            c.execute(text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                " VALUES (:v,:mk,:md,:yr,'update',:o,:n)"), log[i:i + 500])

    print(f"  DONE — version {ver}, {len(updates):,} rows corrected\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
