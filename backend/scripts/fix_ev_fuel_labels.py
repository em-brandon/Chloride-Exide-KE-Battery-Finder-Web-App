"""
fix_ev_fuel_labels.py
---------------------
Label battery-electric vehicles as electric instead of petrol.

THE DEFECT
----------
53 validation rows and 25 vehicle_years rows name a battery-electric car but
carry PETROL in the fuel column:

    NISSAN  E NV 200 VAN GX 5     PETROL     an electric van
    NISSAN  LEAF G                PETROL
    MAZDA   MX 30                 PETROL
    AUDI    Q8 SPORTBACK E-TRON   PETROL

These are also the source of the "engine_cc = 0" rows flagged by the sanity
sweep: a BEV has no displacement, so 0 is correct there and the fuel label is
the thing that is wrong.

THE VARIANTS THAT MUST NOT BE TOUCHED
-------------------------------------
Range-extender cars share the nameplate but genuinely burn petrol:

    BMW   I 3 RANGE EXTENDER          PLUG-IN HYBRID   correct — has a generator
    MAZDA MX 30 ROTARY EV EDITION R   PLUG-IN HYBRID   correct — rotary REx

Matching the nameplate alone would relabel these as pure EVs and erase a real
drivetrain distinction, so REX_MARKERS excludes them. That is why this keys on
an explicit nameplate list rather than anything looser: "EV" appears inside
plenty of trim names that have nothing to do with the drivetrain.

EFFECT ON THE RECOMMENDATION
----------------------------
_preferred_tech() returns MF for EV before any other branch. For the
non-premium makes here the result is unchanged (they already resolved to MF via
the stop-start branch). For premium makes it changes AGM to MF, which is the
intended consequence of the label being right — the battery is re-resolved so
the stored code, technology and Ah stay consistent with each other.

Usage (run from backend/)
-------------------------
    python scripts/fix_ev_fuel_labels.py
    python scripts/fix_ev_fuel_labels.py --execute
"""

from __future__ import annotations

import argparse
import json
import os
import re
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

EV_FUEL = "ELECTRIC(EV)"
# Battery-electric nameplates present in this dataset. Matched on the canonical
# model key, so "E-NV200" and "E NV 200" both hit.
EV_NAMEPLATES = [
    "E NV 200", "LEAF", "ARIYA", "MX 30", "I 3", "IX", "E TRON",
    "EQA", "EQB", "EQC", "EQE", "EQV", "ID 3", "ID 4", "BZ 4 X",
    "SOUL EV", "KONA ELECTRIC", "IONIQ 5", "IONIQ 6", "EV 6", "TAYCAN",
]
# A range extender burns petrol; its plug-in-hybrid label is already correct.
REX_MARKERS = ("RANGE EXTENDER", "REX", "EV EDITION R", "ROTARY", "ROTART")
SCRIPT = "fix_ev_fuel_labels.py"


def is_pure_ev(model: str) -> bool:
    m = _norm_model_key(str(model))
    if any(x in m for x in REX_MARKERS):
        return False
    return any(re.search(rf"(^|\s){re.escape(n)}(\s|$)", m) for n in EV_NAMEPLATES)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    with engine.connect() as conn:
        w = pd.read_sql(
            "SELECT id, make_n, model_n, year, ah, engine_cc, fuel_type,"
            " battery_code, technology FROM web_battery_validation", conn)
        vy = pd.read_sql("SELECT id, make, model, fuel FROM vehicle_years", conn)

    def wrong(fuel) -> bool:
        return "EV" != _norm_fuel(fuel if isinstance(fuel, str) else None)

    w_hit = [r for r in w.itertuples()
             if is_pure_ev(r.model_n) and wrong(r.fuel_type)]
    vy_hit = [r for r in vy.itertuples()
              if is_pure_ev(r.model) and wrong(r.fuel)]

    print(f"web_battery_validation rows to relabel : {len(w_hit):,}")
    print(f"vehicle_years rows to relabel          : {len(vy_hit):,}")
    if not w_hit and not vy_hit:
        print("  nothing to do\n")
        return 0

    updates, audit, moves, examples = [], [], Counter(), []
    for r in w_hit:
        mk = str(r.make_n).upper().strip()
        cc = int(r.engine_cc) if pd.notna(r.engine_cc) else 0
        try:
            pref = _preferred_tech(cc, "EV", int(r.year), mk,
                                   _infer_stop_start(mk, int(r.year), "EV"))
            primary, _ = _select_batteries(int(r.ah), pref, _make_region(mk))
        except Exception:
            moves["resolve_failed"] += 1
            continue
        changed = (primary["battery_code"] != r.battery_code
                   or str(primary["technology"]).upper() != str(r.technology).upper())
        moves["battery_changed" if changed else "fuel_only"] += 1
        updates.append({"id": int(r.id), "fuel_type": EV_FUEL,
                        "battery_code": primary["battery_code"],
                        "technology": primary["technology"],
                        "ah": int(primary["ah"])})
        audit.append({"mk": r.make_n, "md": r.model_n, "yr": int(r.year),
                      "old": {"fuel_type": r.fuel_type,
                              "battery_code": r.battery_code,
                              "technology": r.technology, "ah": int(r.ah)},
                      "new": {"fuel_type": EV_FUEL,
                              "battery_code": primary["battery_code"],
                              "technology": primary["technology"],
                              "ah": int(primary["ah"])}})
        if len(examples) < 10:
            examples.append(f"  {mk:<9}{str(r.model_n)[:30]:<31}{r.year}  "
                            f"{str(r.fuel_type):<15} -> EV   "
                            f"{r.technology} -> {primary['technology']}")

    for k, n in moves.most_common():
        print(f"      {k:<20}{n:>6,}")
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
            {"i": vid, "v": ver, "a": now, "r": f"ev_fuel_{now:%Y%m%d_%H%M%S}",
             "cc": len(updates),
             "n": f"EV fuel labels corrected: {len(updates)} rows",
             "b": SCRIPT})
        for i in range(0, len(updates), 500):
            c.execute(text(
                "UPDATE web_battery_validation SET fuel_type=:fuel_type,"
                " battery_code=:battery_code, technology=:technology, ah=:ah,"
                f" version_id='{vid}' WHERE id=:id"), updates[i:i + 500])
        log = [{"v": vid, "mk": a["mk"], "md": a["md"], "yr": a["yr"],
                "o": json.dumps(a["old"], default=str),
                "n": json.dumps(a["new"], default=str)} for a in audit]
        for i in range(0, len(log), 500):
            c.execute(text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                " VALUES (:v,:mk,:md,:yr,'update',:o,:n)"), log[i:i + 500])
        if vy_hit:
            ids = [int(r.id) for r in vy_hit]
            for i in range(0, len(ids), 500):
                c.execute(text("UPDATE vehicle_years SET fuel = :f"
                               " WHERE id = ANY(:ids)"),
                          {"f": EV_FUEL, "ids": ids[i:i + 500]})

    print(f"  DONE — version {ver}: {len(updates)} validation rows, "
          f"{len(vy_hit)} vehicle_years rows relabelled\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
