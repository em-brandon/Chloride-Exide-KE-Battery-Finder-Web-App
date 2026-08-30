"""
fix_ah_displacement_floor.py
----------------------------
Raise Ah values that are too small for the engine they are fitted to.

THE GAP THIS CLOSES
-------------------
This is the mirror of the kei ceiling in fix_ah_kei_and_oem.py. That script
caps Ah where displacement is legally limited (<=660 cc cannot need 80Ah); this
one puts a floor under it, because the plausibility band cannot see either end.

224 rows carry an engine of 2000 cc or more on a battery of 45Ah or less —
down to a 43Ah, the smallest DIN battery stocked, under a 3.0-litre Audi Q8.
Every one passes the existing 0.5x-2.0x check, because 45 against an expected
55 is a ratio of 0.82, comfortably inside the band. The band is calibrated for
the middle of the range and is simply too loose at the bottom, exactly as it
was at the top.

    AUDI 87 · MARUTI SUZUKI 50 · TOYOTA 39 · NISSAN 11 · HYUNDAI 9 · others 28

This is a live defect, not just a reporting one: matcher.py Layer 0a reads
target_ah straight from the stored battery_code, so a 2.5-litre car resolved to
a 43Ah battery is a recommendation that will struggle to crank it.

THE RULE
--------
Engine >= FLOOR_CC and stored Ah <= FLOOR_AH is implausible, and the row is
re-sized to _target_ah — the same engine/fuel/year figure the app already
serves through its Layer 3 fallback, not a number invented here.

Ah is stored as the SELECTED battery's rating, so the printed figure and the
battery code cannot disagree (see align_ah_to_selected_battery.py).

OEM CONFIRMATION VETO
---------------------
Checked BEFORE a row is treated as wrong. _target_ah is unreliable at both
extremes and over-sizes sports cars and hydrogen/hybrid drivetrains — Exide
lists the Nissan GT-R and Toyota Mirai at 45Ah against a rules estimate of 90
and 95. Both were wrongly quarantined once already on this dataset. If Exide's
own guide confirms the small battery, the guide is right and the rule is wrong.

Usage (run from backend/)
-------------------------
    python scripts/fix_ah_displacement_floor.py
    python scripts/fix_ah_displacement_floor.py --execute
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import Counter, defaultdict
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
from matcher import (_fitment_override, _infer_stop_start, _make_region,
                     _norm_fuel, _norm_model_key, _preferred_tech,
                     _select_batteries, _target_ah)
from scripts.apply_oem_to_staging import MAKE_ALIASES, _compact, oem_head

FLOOR_CC = 2000
FLOOR_AH = 45
OEM_TOLERANCE = 0.15
SCRIPT = "fix_ah_displacement_floor.py"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--table", default="web_battery_validation")
    args = p.parse_args()

    with engine.connect() as conn:
        df = pd.read_sql(text(
            f"SELECT id, make_n, model_n, year, ah, engine_cc, fuel_type,"
            f" battery_code, technology FROM {args.table}"
            f" WHERE engine_cc >= :cc AND ah <= :ah"), conn,
            params={"cc": FLOOR_CC, "ah": FLOOR_AH})
        oem = pd.read_sql(
            "SELECT upper(trim(make)) mk, model, year_from, year_to, ah"
            " FROM oem_fitment WHERE ah IS NOT NULL", conn)

    print(f"rows with engine >= {FLOOR_CC}cc on <= {FLOOR_AH}Ah : {len(df):,}")
    if df.empty:
        return 0

    idx: dict[str, list] = defaultdict(list)
    for r in oem.itertuples():
        idx[r.mk].append((_compact(oem_head(r.model, r.mk)), r.year_from,
                          r.year_to, r.ah))

    def oem_ah(mk: str, model: str, year: int):
        cands = idx.get(MAKE_ALIASES.get(mk, mk)) or idx.get(mk) or []
        toks = str(model).upper().split()
        for n in range(len(toks), 0, -1):
            pre = _compact(" ".join(toks[:n]))
            if len(pre) < (4 if n == 1 else 2):
                continue
            hits = [a for ch, yf, yt, a in cands
                    if ch.startswith(pre)
                    and (pd.isna(yf) or yf <= year) and (pd.isna(yt) or year <= yt)]
            if hits:
                return float(pd.Series(hits).median())
        return None

    updates, audit, reasons, examples = [], [], Counter(), []
    for r in df.itertuples():
        mk = str(r.make_n).upper().strip()
        yr, cc = int(r.year), int(r.engine_cc)
        nf = _norm_fuel(r.fuel_type) if r.fuel_type else ""

        exact = _fitment_override(mk, _norm_model_key(str(r.model_n)), yr)
        if exact and exact[0] and abs(float(exact[0]) - r.ah) / float(exact[0]) <= OEM_TOLERANCE:
            reasons["oem_confirmed_kept"] += 1
            continue
        cand = oem_ah(mk, str(r.model_n), yr)
        if cand is not None and abs(cand - r.ah) / cand <= OEM_TOLERANCE:
            reasons["oem_confirmed_kept"] += 1
            continue

        target = cand if cand is not None else _target_ah(cc, nf, yr)
        if not target:
            reasons["no_target"] += 1
            continue
        try:
            pref = _preferred_tech(cc, nf, yr, mk, _infer_stop_start(mk, yr, nf))
            primary, _ = _select_batteries(int(round(target)), pref, _make_region(mk))
        except Exception:
            reasons["resolve_failed"] += 1
            continue
        stocked = int(primary["ah"])
        if stocked == int(r.ah):
            reasons["already_correct"] += 1
            continue

        reasons["oem_resized" if cand is not None else "rules_resized"] += 1
        updates.append({"id": int(r.id), "ah": stocked,
                        "battery_code": primary["battery_code"],
                        "technology": primary["technology"]})
        audit.append({"mk": r.make_n, "md": r.model_n, "yr": yr,
                      "old": {"ah": int(r.ah), "battery_code": r.battery_code,
                              "technology": r.technology},
                      "new": {"ah": stocked,
                              "battery_code": primary["battery_code"],
                              "technology": primary["technology"]}})
        if len(examples) < 10:
            examples.append(f"  {mk:<13}{str(r.model_n)[:30]:<31}{r.year}  "
                            f"{cc:>4}cc  {int(r.ah):>3} -> {stocked:>3}Ah")

    print(f"  rows to correct : {len(updates):,}")
    for k, n in reasons.most_common():
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
            {"i": vid, "v": ver, "a": now, "r": f"ah_floor_{now:%Y%m%d_%H%M%S}",
             "cc": len(updates),
             "n": (f"Displacement floor (>={FLOOR_CC}cc must exceed {FLOOR_AH}Ah): "
                   f"{len(updates)} rows re-sized"),
             "b": SCRIPT})
        for i in range(0, len(updates), 500):
            c.execute(text(
                f"UPDATE {args.table} SET ah=:ah, battery_code=:battery_code,"
                f" technology=:technology, version_id='{vid}' WHERE id=:id"),
                updates[i:i + 500])
        log = [{"v": vid, "mk": a["mk"], "md": a["md"], "yr": a["yr"],
                "o": json.dumps(a["old"], default=str),
                "n": json.dumps(a["new"], default=str)} for a in audit]
        for i in range(0, len(log), 500):
            c.execute(text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                " VALUES (:v,:mk,:md,:yr,'update',:o,:n)"), log[i:i + 500])

    print(f"  DONE — version {ver}, {len(updates):,} rows re-sized\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
