"""
fix_ah_within_model_spread.py
-----------------------------
Reconcile models whose own years disagree about the battery by a factor of two
or more.

THE PATTERN
-----------
16 models span >=2x in Ah across their own years, and the spread is almost
always an exact doubling:

    SUZUKI     ESCUDO                 35 - 75      25 rows
    TOYOTA     CENTURY SEDAN          50 - 100     21 rows
    DAIHATSU   GRAN MAX               45 - 90      14 rows
    VOLKSWAGEN PASSAT ETSI ELEGANCE   43 - 95      11 rows

An exact 2x clustering is not scatter, it is an artifact: a listing for two
batteries ("2 x 45Ah") scraped as a single 90Ah figure. The same signature
drove the RATIO_HI boundary decision in fix_staging_ah_outliers.py.

WHY NEITHER END CAN BE PICKED BLINDLY
-------------------------------------
The obvious fix — keep the smaller value — is wrong as often as it is right.
Daihatsu Gran Max is a 1.5-litre van, so 45 is correct and 90 is the doubled
reading. Volkswagen Passat is the reverse: 95 is a real Passat battery and 43 is
the smallest DIN we stock, i.e. an undersized row. Picking min would corrupt
the Passat, picking max would corrupt the Gran Max.

So each ROW is judged on its own engine, not on its model's extremes: rows
already agreeing with _target_ah are left alone, and only rows outside the core
band are re-resolved. Exide's guide is consulted first and wins where it
covers the vehicle.

This runs AFTER fix_ah_displacement_floor.py, which removes the undersized end
of several of these spreads on its own.

Usage (run from backend/)
-------------------------
    python scripts/fix_ah_within_model_spread.py
    python scripts/fix_ah_within_model_spread.py --execute
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
from matcher import (_infer_stop_start, _make_region, _norm_fuel,
                     _preferred_tech, _select_batteries, _target_ah)
from scripts.apply_oem_to_staging import MAKE_ALIASES, _compact, oem_head

SPREAD_FACTOR = 2.0
MIN_ROWS = 3
# A row inside this band already agrees with the rules and is left alone; the
# band is tighter than the 0.5-2.0 correction band used elsewhere because here
# we already know the model is internally inconsistent, so "defensible on its
# own" is not good enough — it has to be the value the engine actually implies.
CORE_LO, CORE_HI = 0.75, 1.35
SCRIPT = "fix_ah_within_model_spread.py"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--table", default="web_battery_validation")
    args = p.parse_args()

    with engine.connect() as conn:
        df = pd.read_sql(
            f"SELECT id, make_n, model_n, year, ah, engine_cc, fuel_type,"
            f" battery_code, technology FROM {args.table} WHERE ah IS NOT NULL", conn)
        oem = pd.read_sql(
            "SELECT upper(trim(make)) mk, model, year_from, year_to, ah"
            " FROM oem_fitment WHERE ah IS NOT NULL", conn)
    df["engine_cc"] = pd.to_numeric(df.engine_cc, errors="coerce")
    df["mk"] = df.make_n.str.upper().str.strip()

    g = df.groupby(["mk", "model_n"]).ah.agg(["min", "max", "size"])
    bad_models = set(g[(g["size"] >= MIN_ROWS)
                       & (g["max"] >= SPREAD_FACTOR * g["min"])].index)
    scope = df[[(r.mk, r.model_n) in bad_models for r in df.itertuples()]]

    print(f"models with >={SPREAD_FACTOR:g}x internal spread : {len(bad_models)}")
    print(f"rows in those models                  : {len(scope):,}")
    if scope.empty:
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
    for r in scope.itertuples():
        if pd.isna(r.engine_cc):
            reasons["no_engine_cc_skipped"] += 1
            continue
        cc, yr = int(r.engine_cc), int(r.year)
        nf = _norm_fuel(r.fuel_type) if r.fuel_type else ""
        exp = _target_ah(cc, nf, yr)
        if not exp:
            reasons["no_target"] += 1
            continue
        ratio = r.ah / exp
        if CORE_LO <= ratio <= CORE_HI:
            reasons["agrees_with_rules_kept"] += 1
            continue

        cand = oem_ah(str(r.mk), str(r.model_n), yr)
        target = cand if cand is not None else exp
        try:
            pref = _preferred_tech(cc, nf, yr, str(r.mk),
                                   _infer_stop_start(str(r.mk), yr, nf))
            primary, _ = _select_batteries(int(round(target)), pref,
                                           _make_region(str(r.mk)))
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
        if len(examples) < 12:
            examples.append(f"  {str(r.mk):<12}{str(r.model_n)[:29]:<30}{yr}  "
                            f"{cc:>4}cc  {int(r.ah):>3} -> {stocked:>3}Ah")

    print(f"  rows to correct : {len(updates):,}")
    for k, n in reasons.most_common():
        print(f"      {k:<24}{n:>6,}")
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
            {"i": vid, "v": ver, "a": now, "r": f"ah_spread_{now:%Y%m%d_%H%M%S}",
             "cc": len(updates),
             "n": f"Within-model Ah spread reconciled: {len(updates)} rows",
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

    print(f"  DONE — version {ver}, {len(updates):,} rows reconciled\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
