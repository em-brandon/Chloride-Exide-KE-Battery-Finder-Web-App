"""
fix_kei_diesel_mislabel.py
--------------------------
Relabel kei-class vehicles wrongly recorded as diesel, and re-size the battery
that mislabel produced.

THE DEFECT
----------
30 validation rows (42 in vehicle_years) are 658 cc and marked DIESEL:

    NISSAN NT100 CLIPPER DX     658 cc  DIESEL  50Ah
    TOYOTA PIXIS TRUCK EXTRA    658 cc  DIESEL  50Ah
    SUZUKI ALTO VAN VP          658 cc  DIESEL

Japan's kei class is capped at 660 cc and is petrol in practice; none of these
three has ever been sold with a diesel engine. The label is simply wrong.

WHY IT SURVIVED THE KEI CEILING
-------------------------------
fix_ah_kei_and_oem.py caps kei vehicles at KEI_AH_MAX (46Ah). These rows sit at
50Ah and were caught by that test — but its replacement value comes from
_target_ah, and _target_ah reads the same wrong fuel: the diesel bracket for a
sub-1000 cc engine returns 50, not the petrol bracket's 45. So the script
"corrected" 50 back to 50 and the row survived, looking fixed.

That is the general shape worth remembering: a downstream ceiling cannot repair
a row whose input is wrong, because the rule it falls back to reads the same
bad input. The fuel label has to be fixed first, and then the Ah follows from
it — which is what this script does, in that order.

Usage (run from backend/)
-------------------------
    python scripts/fix_kei_diesel_mislabel.py
    python scripts/fix_kei_diesel_mislabel.py --execute
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
from matcher import (_infer_stop_start, _make_region, _preferred_tech,
                     _select_batteries, _target_ah)

KEI_CC_MAX = 660
NEW_FUEL = "PETROL"
SCRIPT = "fix_kei_diesel_mislabel.py"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    with engine.connect() as conn:
        w = pd.read_sql(text(
            "SELECT id, make_n, model_n, year, ah, engine_cc, fuel_type,"
            " battery_code, technology FROM web_battery_validation"
            " WHERE engine_cc > 0 AND engine_cc <= :cc"
            "   AND upper(fuel_type) LIKE '%DIESEL%'"), conn,
            params={"cc": KEI_CC_MAX})
        vy = pd.read_sql(text(
            "SELECT id FROM vehicle_years"
            " WHERE engine_capacity > 0 AND engine_capacity <= :cc"
            "   AND upper(fuel) LIKE '%DIESEL%'"), conn, params={"cc": KEI_CC_MAX})

    print(f"kei rows marked diesel — validation {len(w):,}, vehicle_years {len(vy):,}")
    if w.empty and vy.empty:
        print("  nothing to do\n")
        return 0

    updates, audit, examples = [], [], []
    for r in w.itertuples():
        mk = str(r.make_n).upper().strip()
        cc, yr = int(r.engine_cc), int(r.year)
        target = _target_ah(cc, NEW_FUEL, yr)
        try:
            pref = _preferred_tech(cc, NEW_FUEL, yr, mk,
                                   _infer_stop_start(mk, yr, NEW_FUEL))
            primary, _ = _select_batteries(int(target), pref, _make_region(mk))
        except Exception:
            continue
        updates.append({"id": int(r.id), "fuel_type": NEW_FUEL,
                        "ah": int(primary["ah"]),
                        "battery_code": primary["battery_code"],
                        "technology": primary["technology"]})
        audit.append({"mk": r.make_n, "md": r.model_n, "yr": yr,
                      "old": {"fuel_type": r.fuel_type, "ah": int(r.ah),
                              "battery_code": r.battery_code,
                              "technology": r.technology},
                      "new": {"fuel_type": NEW_FUEL, "ah": int(primary["ah"]),
                              "battery_code": primary["battery_code"],
                              "technology": primary["technology"]}})
        if len(examples) < 8:
            examples.append(f"  {mk:<8}{str(r.model_n)[:26]:<27}{yr}  {cc}cc  "
                            f"DIESEL->PETROL  {int(r.ah)} -> {int(primary['ah'])}Ah")

    print(f"  validation rows to correct : {len(updates):,}")
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
            {"i": vid, "v": ver, "a": now, "r": f"kei_diesel_{now:%Y%m%d_%H%M%S}",
             "cc": len(updates),
             "n": f"Kei vehicles mislabelled diesel: {len(updates)} rows",
             "b": SCRIPT})
        for i in range(0, len(updates), 500):
            c.execute(text(
                "UPDATE web_battery_validation SET fuel_type=:fuel_type, ah=:ah,"
                " battery_code=:battery_code, technology=:technology,"
                f" version_id='{vid}' WHERE id=:id"), updates[i:i + 500])
        log = [{"v": vid, "mk": a["mk"], "md": a["md"], "yr": a["yr"],
                "o": json.dumps(a["old"], default=str),
                "n": json.dumps(a["new"], default=str)} for a in audit]
        for i in range(0, len(log), 500):
            c.execute(text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                " VALUES (:v,:mk,:md,:yr,'update',:o,:n)"), log[i:i + 500])
        if len(vy):
            ids = [int(i) for i in vy.id]
            for i in range(0, len(ids), 500):
                c.execute(text("UPDATE vehicle_years SET fuel = :f"
                               " WHERE id = ANY(:ids)"),
                          {"f": NEW_FUEL, "ids": ids[i:i + 500]})

    print(f"  DONE — version {ver}: {len(updates)} validation rows, "
          f"{len(vy)} vehicle_years rows relabelled\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
