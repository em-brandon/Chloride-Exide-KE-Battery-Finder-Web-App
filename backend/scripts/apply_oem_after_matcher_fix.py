"""
apply_oem_after_matcher_fix.py
------------------------------
Apply manufacturer capacities to rows the OEM matcher could not previously see.

WHY THIS RUN EXISTS
-------------------
Three faults in the name matching hid large parts of the guide from every
earlier correction pass:

    VOLKSWAGEN     all 6,151 guide entries are written "VW ..."
    MERCEDES-BENZ  5,169 entries are misspelled "MERCEDEZ-BENZ"
    LEXUS          models are named in two letters (CT, ES, RX)
    JEEP           our own records prefix every model with "CHRYSLER"

With those fixed the guide can now size 12,861 of our rows, up from roughly
11,800 — and, more importantly, it can now speak about vehicles it was silent
on when their capacity was first decided. 502 of those rows disagree with the
stored value by more than 35%.

WHY NOT SIMPLY TAKE THE GUIDE EVERY TIME
----------------------------------------
Because the prefix match is nameplate-level, not trim-exact: a short key pulls
in every engine variant of a model and returns their median. That median is far
better than nothing, and worse than a value that is already right.

Both failure directions are real in this data:

    HYUNDAI SANTA FE CALIGRAPHY   stored 50Ah, guide 89-95Ah   stored is wrong
    TOYOTA  MIRAI                 stored 45Ah, guide 40Ah      guide median is wrong

Mirai is the cautionary case. Its exact fitment entry says 45Ah, but the Mirai
nameplate median across all variants comes out at 40, so a blind apply would
quietly damage a row that earlier work had already got right.

THE TIE-BREAK
-------------
Engine displacement decides, because it is the one piece of evidence
independent of both candidates:

  1. If an EXACT fitment entry exists for this vehicle, it wins outright. It is
     trim-specific, so no tie-break is needed or wanted.
  2. Otherwise, when the nameplate median disagrees by more than THRESHOLD,
     keep whichever of the two sits closer to _target_ah for that engine.
     A Santa Fe's 2.4 litres supports ~70Ah, so the guide's 89 beats the stored
     50. A Mirai's 3.5 litres nominally supports ~95Ah, so the stored 45 beats
     the guide's 40 — and the row is left alone.

Rows within THRESHOLD are untouched: small differences are the stocked-size
rounding, not disagreement.

Usage (run from backend/)
-------------------------
    python scripts/apply_oem_after_matcher_fix.py
    python scripts/apply_oem_after_matcher_fix.py --execute
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
from scripts.apply_oem_to_staging import (MAKE_ALIASES, _compact, oem_head,
                                          oem_prefixes)

THRESHOLD = 0.35
SCRIPT = "apply_oem_after_matcher_fix.py"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--table", default="web_battery_validation")
    args = p.parse_args()

    with engine.connect() as conn:
        w = pd.read_sql(
            f"SELECT id, make_n, model_n, year, ah, engine_cc, fuel_type,"
            f" battery_code, technology FROM {args.table} WHERE ah IS NOT NULL",
            conn)
        oem = pd.read_sql(
            "SELECT upper(trim(make)) mk, model, year_from, year_to, ah"
            " FROM oem_fitment WHERE ah IS NOT NULL", conn)
    w["engine_cc"] = pd.to_numeric(w.engine_cc, errors="coerce")

    idx: dict[str, list] = defaultdict(list)
    for r in oem.itertuples():
        idx[r.mk].append((_compact(oem_head(r.model, r.mk)), r.year_from,
                          r.year_to, r.ah))

    def nameplate_ah(mk: str, model: str, year: int):
        cands = idx.get(MAKE_ALIASES.get(mk, mk)) or idx.get(mk) or []
        for key, exact_only in oem_prefixes(mk, model):
            hits = [a for ch, yf, yt, a in cands
                    if ((ch == key) if exact_only else ch.startswith(key))
                    and (pd.isna(yf) or yf <= year) and (pd.isna(yt) or year <= yt)]
            if hits:
                return float(pd.Series(hits).median())
        return None

    updates, audit, why, examples = [], [], Counter(), []
    for r in w.itertuples():
        mk = str(r.make_n).upper().strip()
        yr = int(r.year)
        cc = int(r.engine_cc) if pd.notna(r.engine_cc) else 0
        nf = _norm_fuel(r.fuel_type) if r.fuel_type else ""
        stored = int(r.ah)

        target = None
        exact = _fitment_override(mk, _norm_model_key(str(r.model_n)), yr)
        if exact and exact[0]:
            target, tier = float(exact[0]), "exact_fitment"
        else:
            cand = nameplate_ah(mk, str(r.model_n), yr)
            if cand is None:
                why["no_guide_entry"] += 1
                continue
            if abs(cand - stored) / cand <= THRESHOLD:
                why["within_threshold_kept"] += 1
                continue
            rules = _target_ah(cc, nf, yr) if cc else None
            if rules:
                # Displacement referees. See module docstring.
                if abs(stored - rules) <= abs(cand - rules):
                    why["stored_closer_to_engine_kept"] += 1
                    continue
            elif cc == 0:
                why["no_engine_cc_kept"] += 1
                continue
            target, tier = cand, "nameplate_median"

        try:
            pref = _preferred_tech(cc, nf, yr, mk, _infer_stop_start(mk, yr, nf))
            primary, _ = _select_batteries(int(round(target)), pref,
                                           _make_region(mk))
        except Exception:
            why["resolve_failed"] += 1
            continue
        stocked = int(primary["ah"])
        if stocked == stored:
            why["already_correct"] += 1
            continue

        why[tier] += 1
        updates.append({"id": int(r.id), "ah": stocked,
                        "battery_code": primary["battery_code"],
                        "technology": primary["technology"]})
        audit.append({"mk": r.make_n, "md": r.model_n, "yr": yr,
                      "old": {"ah": stored, "battery_code": r.battery_code,
                              "technology": r.technology},
                      "new": {"ah": stocked,
                              "battery_code": primary["battery_code"],
                              "technology": primary["technology"]}})
        if len(examples) < 12:
            examples.append(f"  {mk:<13}{str(r.model_n)[:30]:<31}{yr}  "
                            f"{cc or '?':>4}cc  {stored:>3} -> {stocked:>3}Ah  {tier}")

    print(f"rows examined   : {len(w):,}")
    print(f"rows to correct : {len(updates):,}")
    for k, n in why.most_common():
        print(f"      {k:<30}{n:>6,}")
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
            {"i": vid, "v": ver, "a": now, "r": f"oem_rematch_{now:%Y%m%d_%H%M%S}",
             "cc": len(updates),
             "n": (f"OEM capacities applied after name-matching fix: "
                   f"{len(updates)} rows"),
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

    print(f"  DONE — version {ver}, {len(updates):,} rows corrected\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
