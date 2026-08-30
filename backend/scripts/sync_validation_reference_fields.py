"""
sync_validation_reference_fields.py
-----------------------------------
Make web_battery_validation's engine_cc and fuel_type agree with vehicle_years.

WHY THEY DIVERGE
----------------
web_battery_validation copies engine_cc and fuel_type from vehicle_years at the
moment the pipeline runs. vehicle_years has been edited many times since — year
cleanups, model renames, the EV and kei-diesel fuel corrections — so the copies
are stale on 265 rows:

    fuel   169 rows   LANDROVER DEFENDER: validation PETROL, reference DIESEL
    cc      96 rows   MAZDA CX 3 XD:      validation 1756,   reference 1498

WHY vehicle_years WINS
----------------------
matcher._vehicles() reads engine_capacity and fuel from vehicle_years at request
time. It never reads the copies in web_battery_validation. So when the two
disagree, the exported guide is describing a car the app does not recognise —
it would print "petrol" beside a battery the app chose on diesel rules. The
reference table is the one that decides behaviour, so it is the one the report
must match.

WHAT IS DELIBERATELY NOT RE-DERIVED
-----------------------------------
Ah is KEPT as stored. It is overwhelmingly Exide fitment data (57% of rows),
which is better evidence than any rule computed from displacement — re-running
_target_ah against the corrected engine size would discard that and re-introduce
the under-sizing this dataset spent the night removing.

battery_code and technology ARE re-resolved, at the existing Ah, because the
technology preference depends on fuel: a row corrected from petrol to diesel may
warrant AGM rather than MF. Capacity is preserved; only the chemistry follows
the corrected fuel.

Usage (run from backend/)
-------------------------
    python scripts/sync_validation_reference_fields.py
    python scripts/sync_validation_reference_fields.py --execute
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
from matcher import (_infer_stop_start, _make_region, _norm_fuel, _norm_model_key,
                     _preferred_tech, _select_batteries)

SCRIPT = "sync_validation_reference_fields.py"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    with engine.connect() as conn:
        w = pd.read_sql(
            "SELECT id, make_n, model_n, year, ah, engine_cc, fuel_type,"
            " battery_code, technology FROM web_battery_validation", conn)
        vy = pd.read_sql(
            "SELECT upper(trim(make)) mk, model, year, engine_capacity, fuel"
            " FROM vehicle_years", conn)

    def K(mk, md, yr):
        return (str(mk).upper().strip(), _norm_model_key(str(md)), int(yr))

    ref = {K(r.mk, r.model, r.year): (r.engine_capacity, r.fuel)
           for r in vy.itertuples()}

    updates, audit, moves, examples = [], [], Counter(), []
    for r in w.itertuples():
        t = ref.get(K(r.make_n, r.model_n, r.year))
        if t is None:
            moves["no_reference_row"] += 1
            continue
        vcc, vfuel = t
        new_cc = int(vcc) if pd.notna(vcc) else None
        old_cc = int(r.engine_cc) if pd.notna(r.engine_cc) else None
        cc_diff = new_cc != old_cc
        fuel_diff = str(vfuel).upper() != str(r.fuel_type).upper()
        if not (cc_diff or fuel_diff):
            continue

        mk, yr = str(r.make_n).upper().strip(), int(r.year)
        nf = _norm_fuel(vfuel) if isinstance(vfuel, str) else ""
        try:
            pref = _preferred_tech(new_cc or 0, nf, yr, mk,
                                   _infer_stop_start(mk, yr, nf))
            # Same Ah, re-picked chemistry. See module docstring.
            primary, _ = _select_batteries(int(r.ah), pref, _make_region(mk))
        except Exception:
            moves["resolve_failed"] += 1
            continue

        moves["fuel" if fuel_diff else "engine_cc"] += 1
        if str(primary["technology"]).upper() != str(r.technology).upper():
            moves["technology_changed"] += 1
        updates.append({"id": int(r.id), "engine_cc": new_cc,
                        "fuel_type": vfuel if isinstance(vfuel, str) else None,
                        "battery_code": primary["battery_code"],
                        "technology": primary["technology"],
                        "ah": int(primary["ah"])})
        audit.append({"mk": r.make_n, "md": r.model_n, "yr": yr,
                      "old": {"engine_cc": old_cc, "fuel_type": r.fuel_type,
                              "battery_code": r.battery_code,
                              "technology": r.technology, "ah": int(r.ah)},
                      "new": {"engine_cc": new_cc, "fuel_type": vfuel,
                              "battery_code": primary["battery_code"],
                              "technology": primary["technology"],
                              "ah": int(primary["ah"])}})
        if len(examples) < 10:
            what = (f"{r.fuel_type}->{vfuel}" if fuel_diff
                    else f"{old_cc}->{new_cc}cc")
            examples.append(f"  {mk:<11}{str(r.model_n)[:30]:<31}{yr}  {what}")

    print(f"rows to sync : {len(updates):,}")
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
            {"i": vid, "v": ver, "a": now, "r": f"ref_sync_{now:%Y%m%d_%H%M%S}",
             "cc": len(updates),
             "n": (f"Synced engine_cc/fuel from vehicle_years: "
                   f"{len(updates)} rows"),
             "b": SCRIPT})
        for i in range(0, len(updates), 500):
            c.execute(text(
                "UPDATE web_battery_validation SET engine_cc=:engine_cc,"
                " fuel_type=:fuel_type, battery_code=:battery_code,"
                f" technology=:technology, ah=:ah, version_id='{vid}'"
                f" WHERE id=:id"), updates[i:i + 500])
        log = [{"v": vid, "mk": a["mk"], "md": a["md"], "yr": a["yr"],
                "o": json.dumps(a["old"], default=str),
                "n": json.dumps(a["new"], default=str)} for a in audit]
        for i in range(0, len(log), 500):
            c.execute(text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                " VALUES (:v,:mk,:md,:yr,'update',:o,:n)"), log[i:i + 500])

    print(f"  DONE — version {ver}, {len(updates):,} rows synced\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
