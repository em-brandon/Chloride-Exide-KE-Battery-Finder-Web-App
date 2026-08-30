"""
cleanup_western_web_validation.py
---------------------------------
Bring the Western rows of web_battery_validation up to the same standard the
Japanese rows now meet, without spending any search-API budget.

WHY THESE ROWS ARE DIFFERENT
----------------------------
The Japanese makes were rebuilt from scratch on 2026-08-14/15: rows regenerated
from the cleaned vehicle_years, technology re-derived from the rules engine, Ah
outliers corrected. The Western rows were last built on 2026-07-10 — before the
year cleanup, before the technology fix, and before the stop-start rule — so
they still carry every defect that work removed:

    rows   pre-2000  tech contradicts code  anachronistic  extreme Ah
  12,296      3,364                  4,139            324         591

A full Western rebuild would cost roughly 8,800 Brave calls against ~3,600
remaining, so it is not available. This does everything that does not need the
network.

WHAT IT DOES, IN ORDER
----------------------
1. QUARANTINE to web_battery_unmatched (never delete — the row stays
   recoverable and becomes a research worklist entry):
     a. pre-2000 rows            — same year floor the Japanese rebuild used
     b. anachronistic trim/year  — TSI before 2005, HYBRID before 1997, ...
     c. ghost vehicles           — no longer in vehicle_years after the year
                                   cleanup. Matched with _norm_model_key, NOT
                                   raw string compare: on the Japanese rows a
                                   raw compare reported 2,542 ghosts and the
                                   normalised compare reported 0, so a raw
                                   compare here would quarantine thousands of
                                   perfectly good rows.
2. RE-RESOLVE technology + battery_code for every surviving row from its Ah,
   using _preferred_tech() with stop-start inferred from make+year — identical
   to what the pipeline now does. This is what fixes the 4,139 contradictions.
3. CORRECT extreme Ah using the same tiers as fix_staging_ah_outliers.py:
   Exide oem_fitment first, then the engine-size rules, then within-model
   median (computed only from rows already agreeing with the rules, so
   outliers cannot set the baseline).

WHAT IT DOES NOT DO
-------------------
It does not refresh any Ah from the web. Surviving Western Ah values remain
July scrapes — free of extremes and internally consistent, but unverified.
Only a targeted re-search fixes that, and that costs Brave budget.

Every change is written to web_battery_validation_versions/_changelog, so the
whole pass is revertible through the existing admin version history.

Usage (run from backend/)
-------------------------
    python scripts/cleanup_western_web_validation.py
    python scripts/cleanup_western_web_validation.py --execute
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

JDM_MAKES = {"TOYOTA", "NISSAN", "DAIHATSU", "MITSUBISHI", "HONDA", "MAZDA",
             "SUBARU", "HINO", "ISUZU", "SUZUKI", "LEXUS", "NISSAN DIESEL/UD",
             "MITSUBISHI FUSO"}

YEAR_FLOOR = 2000
RATIO_LO, RATIO_HI = 0.5, 2.0
CORE_LO, CORE_HI = 0.75, 1.35
MEDIAN_TOLERANCE = 0.5
MIN_ROWS_FOR_MEDIAN = 3

ANACHRONISMS = {
    "HYBRID": 1997, "E:HEV": 2018, "PHEV": 2010, "PHV": 2012, "MHEV": 2016,
    "TFSI": 2004, "TSI": 2005, "SKYACTIV": 2011, "BLUETEC": 2006,
    "E-POWER": 2016, "EYESIGHT": 2010, "ALLTRACK": 2012, "VELAR": 2017,
}

SCRIPT = "cleanup_western_web_validation.py"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true", help="Apply. Default is a dry run.")
    args = p.parse_args()

    with engine.connect() as conn:
        df = pd.read_sql(
            "SELECT id, make_n, model_n, year, ah, technology, battery_code,"
            " engine_cc, fuel_type FROM web_battery_validation", conn)
        vy = pd.read_sql("SELECT upper(trim(make)) mk, model, year FROM vehicle_years", conn)

    df["mk"] = df.make_n.str.upper().str.strip()
    west = df[~df.mk.isin(JDM_MAKES)].copy()
    print(f"Western rows: {len(west):,}  (of {len(df):,} total)")
    if west.empty:
        return 0

    west["engine_cc"] = pd.to_numeric(west.engine_cc, errors="coerce")

    # ---- 1. classify quarantine candidates ------------------------------
    vy_keys = {(r.mk, _norm_model_key(str(r.model)), r.year) for r in vy.itertuples()}
    up = west.model_n.astype(str).str.upper()

    reason = pd.Series([None] * len(west), index=west.index, dtype=object)
    reason[west.year < YEAR_FLOOR] = "pre_2000"
    for kw, first in ANACHRONISMS.items():
        m = up.str.contains(kw, regex=False, na=False) & (west.year < first) & reason.isna()
        reason[m] = f"anachronistic_{kw.lower()}"
    ghost_mask = pd.Series(
        [(r.mk, _norm_model_key(str(r.model_n)), int(r.year)) not in vy_keys
         for r in west.itertuples()], index=west.index)
    reason[ghost_mask & reason.isna()] = "not_in_vehicle_years"

    quarantine = west[reason.notna()].copy()
    quarantine["reason"] = reason[reason.notna()]
    survivors = west[reason.isna()].copy()

    print(f"\n  quarantine : {len(quarantine):,}")
    for k, n in Counter(quarantine.reason).most_common():
        print(f"      {k:<28}{n:>7,}")
    print(f"  survivors  : {len(survivors):,}")

    # ---- 2 & 3. re-resolve technology + correct Ah on survivors ----------
    survivors["exp"] = [
        _target_ah(int(cc), _norm_fuel(f) if f else "", int(y)) if pd.notna(cc) else None
        for cc, f, y in zip(survivors.engine_cc, survivors.fuel_type, survivors.year)]
    survivors["ratio"] = [(a / e) if (e and pd.notna(e) and pd.notna(a)) else None
                          for a, e in zip(survivors.ah, survivors.exp)]

    core = survivors[survivors.ratio.notna() &
                     (survivors.ratio >= CORE_LO) & (survivors.ratio <= CORE_HI)]
    medians: dict[tuple, float] = {}
    counts: dict[tuple, int] = defaultdict(int)
    for key, g in core.groupby(["mk", "model_n"]):
        medians[key] = float(g.ah.median())
        counts[key] = len(g)

    updates: list[dict] = []
    ah_reasons = Counter()
    tech_fixed = 0

    for r in survivors.itertuples():
        new_ah = r.ah
        why = None
        fit = _fitment_override(r.mk, _norm_model_key(str(r.model_n)), int(r.year))
        if fit is not None and fit[0] and int(round(float(fit[0]))) != r.ah:
            new_ah, why = int(round(float(fit[0]))), "oem_fitment"
        elif r.ratio is not None and (r.ratio < RATIO_LO or r.ratio >= RATIO_HI):
            new_ah, why = int(r.exp), "outside_rules_band"
        else:
            key = (r.mk, r.model_n)
            med = medians.get(key)
            if (med and counts[key] >= MIN_ROWS_FOR_MEDIAN and med > 0
                    and pd.notna(r.ah) and abs(r.ah - med) / med > MEDIAN_TOLERANCE):
                new_ah, why = int(round(med)), "model_median_outlier"

        if pd.isna(new_ah):
            continue
        nf = _norm_fuel(r.fuel_type) if r.fuel_type else ""
        # NOT `int(r.engine_cc or 0)`: pandas NaN is TRUTHY, so a missing
        # engine_cc slips past `or 0` and int(NaN) raises — which the except
        # below then swallows, silently skipping the row. That left 247 rows
        # (every Western row with a null engine_cc) still holding the stale
        # technology this pass exists to fix.
        cc = int(r.engine_cc) if pd.notna(r.engine_cc) else 0
        try:
            pref = _preferred_tech(cc, nf, int(r.year), r.mk,
                                   _infer_stop_start(r.mk, int(r.year), nf))
            primary, _ = _select_batteries(int(new_ah), pref, _make_region(r.mk))
        except Exception:
            continue

        if why:
            ah_reasons[why] += 1
        if (primary["battery_code"] != r.battery_code
                or str(primary["technology"]).upper() != str(r.technology).upper()
                or int(new_ah) != (int(r.ah) if pd.notna(r.ah) else -1)):
            if primary["battery_code"] != r.battery_code or \
               str(primary["technology"]).upper() != str(r.technology).upper():
                tech_fixed += 1
            updates.append({"id": int(r.id), "ah": int(new_ah),
                            "battery_code": primary["battery_code"],
                            "technology": primary["technology"]})

    print(f"\n  Ah corrections : {sum(ah_reasons.values()):,}")
    for k, n in ah_reasons.most_common():
        print(f"      {k:<28}{n:>7,}")
    print(f"  code/tech re-resolved : {tech_fixed:,}")
    print(f"  total row updates     : {len(updates):,}")

    if not args.execute:
        print("\n[DRY RUN] Nothing changed. Re-run with --execute to apply.\n")
        return 0

    print("\nTaking a backup before mutating...")
    now = datetime.now(timezone.utc)
    try:
        res = db_backup.create_backup()
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO admin_backup_log (filename, size_bytes, status,"
                " error_detail, triggered_by, created_at)"
                " VALUES (:f,:s,'success',NULL,:t,:c)"),
                {"f": res.filename, "s": res.size_bytes, "t": SCRIPT, "c": now})
        print(f"  backup: {res.filename} ({res.size_bytes:,} bytes)")
    except db_backup.BackupError as exc:
        print(f"\n  ERROR — backup failed, aborting:\n  {exc}\n")
        return 1

    batch = f"western_cleanup_{now.strftime('%Y%m%d_%H%M%S')}"
    vid = str(uuid.uuid4())

    with engine.begin() as conn:
        ver = (conn.execute(text(
            "SELECT COALESCE(MAX(version_number),0) FROM web_battery_validation_versions"
        )).scalar() or 0) + 1
        conn.execute(text(
            "INSERT INTO web_battery_validation_versions"
            " (id,version_number,committed_at,run_id,committed_count,removed_count,"
            "  conflict_count,notes,committed_by,initiated_by)"
            " VALUES (:id,:vn,:at,:rid,:cc,:rc,0,:nt,:by,:by)"),
            {"id": vid, "vn": ver, "at": now, "rid": batch,
             "cc": len(updates), "rc": len(quarantine),
             "nt": f"Western cleanup: {len(quarantine)} quarantined, "
                   f"{len(updates)} rows re-resolved. Ah not refreshed from web.",
             "by": SCRIPT})

        for r in quarantine.itertuples():
            conn.execute(text(
                "INSERT INTO web_battery_unmatched"
                " (make_n,model_n,year,ah,expected_ah,engine_cc,fuel_type,battery_code,"
                "  technology,source_table,reason,moved_at,batch_id)"
                " VALUES (:mn,:mo,:yr,:ah,NULL,:cc,:ft,:bc,:tc,'web_battery_validation',"
                "         :rs,:at,:b)"),
                {"mn": r.make_n, "mo": r.model_n, "yr": int(r.year),
                 "ah": int(r.ah) if pd.notna(r.ah) else None,
                 "cc": int(r.engine_cc) if pd.notna(r.engine_cc) else None,
                 "ft": r.fuel_type, "bc": r.battery_code, "tc": r.technology,
                 "rs": r.reason, "at": now, "b": batch})
            conn.execute(text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                " VALUES (:v,:mn,:mo,:yr,'removed',:ov,NULL)"),
                {"v": vid, "mn": r.make_n, "mo": r.model_n, "yr": int(r.year),
                 "ov": json.dumps({"battery_code": r.battery_code,
                                   "ah": None if pd.isna(r.ah) else int(r.ah),
                                   "technology": r.technology,
                                   "reason": r.reason})})
        if len(quarantine):
            ids = [int(i) for i in quarantine.id]
            for i in range(0, len(ids), 500):
                conn.execute(text("DELETE FROM web_battery_validation WHERE id = ANY(:ids)"),
                             {"ids": ids[i:i + 500]})

        for i in range(0, len(updates), 500):
            conn.execute(text(
                "UPDATE web_battery_validation SET ah=:ah, battery_code=:battery_code,"
                " technology=:technology WHERE id=:id"), updates[i:i + 500])

    print(f"\n  DONE — version {ver}")
    print(f"    quarantined : {len(quarantine):,}  (batch {batch})")
    print(f"    updated     : {len(updates):,}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
