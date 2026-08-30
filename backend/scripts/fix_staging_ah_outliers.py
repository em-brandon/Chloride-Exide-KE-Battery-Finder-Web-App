"""
fix_staging_ah_outliers.py
--------------------------
Correct implausible Ah values in web_battery_staging before they are committed
to web_battery_validation.

WHY
---
Ah is the one figure taken from the web, and it is scraped from search-result
snippets rather than any authoritative source. Nothing validates it beyond a
20-250 absolute range, which is far too loose: a Mitsubishi Minicab (a kei
truck) staged at 200Ah and a Hino Profia (a heavy truck) at 26Ah both pass
that check untouched. Same model, different generations, wildly different
answers depending on which page the search happened to rank first.

These are the errors most likely to be noticed in a review of the exported
fitment guide, and they are also live defects: matcher.py's Layer 0a takes
target_ah straight from the stored battery_code, so a 26Ah heavy truck is a
recommendation that will not start the vehicle.

HOW A ROW IS JUDGED, IN ORDER
-----------------------------
1. oem_fitment covers it  -> use Exide's own Ah. Real manufacturer fitment
   data beats a scrape outright. (Coverage is limited — roughly 7% on a
   Western sample — so this tier is authoritative but narrow.)
2. Scrape agrees with the rules (within RATIO_LO..RATIO_HI of _target_ah)
   -> keep the scrape. The web genuinely adds precision here, and _target_ah
   is deliberately coarse.
3. Scrape is outside that band -> replace with _target_ah, the same
   engine-size/fuel/year figure the app already serves through its Layer 3
   fallback. Not a number invented for the report.
4. Scrape sits in the band but contradicts its own model's other years by
   more than MEDIAN_TOLERANCE -> replace with the model's median Ah. This
   catches the "Passo 35/38/40/75" shape that tier 3 misses because each
   individual value looks defensible.

Rows are CORRECTED, never deleted — the vehicle stays in the report, and
every resulting figure traces to Exide data or documented rules.

battery_code and technology are re-resolved from the corrected Ah, since both
derive from it; leaving them stale would reintroduce exactly the
code/technology contradiction the client originally flagged.

Run this AFTER the pipeline stages rows and BEFORE committing staging to
master.

Usage (run from backend/)
-------------------------
    python scripts/fix_staging_ah_outliers.py
    python scripts/fix_staging_ah_outliers.py --execute
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

TABLE = "web_battery_staging"

# Keep the scrape inside this band of the rules figure. _target_ah is coarse
# by design, so a moderately larger battery is normal and not worth
# overwriting; only clear disagreement is corrected.
RATIO_LO, RATIO_HI = 0.5, 2.0
# The band is treated as EXCLUSIVE at the top (ratio >= RATIO_HI is corrected).
# Every outlier left after the first pass sat at exactly 2.0x — a Daihatsu Boon
# (996 cc) staged at 90Ah against an expected 45. An exact doubling clustering
# like that is a systematic artifact (a "2 x 45Ah" listing read as one 90Ah
# battery), not scatter, so the boundary itself is the wrong side of the line.
# Tightening RATIO_HI to 1.8 instead would sweep in ~1,274 rows in the
# 1.35-2.0 range, 469 of them small cars whose slightly-larger battery is
# legitimate — far more collateral damage than the 136 rows it would fix.
#
# Medians are taken from a TIGHTER core band than the correction band: a row
# sitting exactly at the boundary is not evidence of anything, and with four
# bad 90Ah rows against two correct 40Ah rows it would otherwise set the
# median to 90 and drag the good rows up to match it.
CORE_LO, CORE_HI = 0.75, 1.35
# Within-model consistency: how far a row may sit from its model's median
# before it is treated as the odd one out rather than a real generation change.
MEDIAN_TOLERANCE = 0.5
MIN_ROWS_FOR_MEDIAN = 3


def resolve(ah: int, make_n: str, engine_cc, fuel_type, year):
    """Re-pick battery_code + technology for a corrected Ah (same rule as the pipeline).

    Returns the Ah of the battery actually SELECTED, not the Ah asked for. We
    stock a fixed set of sizes, so a request for Exide's 82Ah resolves to the
    80Ah battery we sell — and storing 82 next to an 80Ah battery code makes
    the exported guide contradict itself on the page. Same reasoning as
    fix_unchecked_ah_via_oem.py, which handles the BMW i3 case (Exide 21Ah,
    smallest DIN battery stocked 43Ah).
    """
    nf = _norm_fuel(fuel_type) if fuel_type else ""
    pref = _preferred_tech(int(engine_cc or 0), nf, year, make_n,
                           _infer_stop_start(make_n, year, nf))
    primary, _ = _select_batteries(int(ah), pref, _make_region(make_n))
    return int(primary["ah"]), primary["battery_code"], primary["technology"]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true", help="Apply. Default is a dry run.")
    p.add_argument("--table", default=TABLE, help="Target table (default web_battery_staging).")
    p.add_argument("--no-median", action="store_true",
                   help="Skip the within-model median tier (tiers 1-3 only).")
    args = p.parse_args()

    # The median tier assumes a model's plausible rows are its CORRECT rows.
    # That holds for a fresh staging batch and does NOT hold on the live table:
    # a genuinely undersized row whose Ah still sits inside the rules band reads
    # as plausible, joins the sample, and can pull the median below the model's
    # real value — live Audi A3 rows on a 43Ah battery would otherwise drag
    # correct 72Ah siblings down to 43. Use --no-median against live, where
    # tiers 1-3 (Exide, then the rules band) are self-contained per row.

    with engine.connect() as conn:
        df = pd.read_sql(
            f"SELECT id, make_n, model_n, year, ah, engine_cc, fuel_type,"
            f" battery_code, technology FROM {args.table} WHERE ah IS NOT NULL", conn)
    print(f"rows in {args.table}: {len(df):,}")
    if df.empty:
        return

    df["engine_cc"] = pd.to_numeric(df["engine_cc"], errors="coerce")

    # Model medians, for the within-model consistency tier.
    #
    # CRITICAL: the median must be taken over PLAUSIBLE rows only. Taking it
    # over every row lets the outliers set the baseline and then spreads them:
    # DAIHATSU ALTIS G stages mostly 200Ah (wrong, expected ~80), so a raw
    # median is 200 and the one correct 90Ah row gets "corrected" up to 200 —
    # the exact inverse of the intended fix. Restrict the sample to rows that
    # already agree with the rules figure, and skip the tier entirely for a
    # model with too few such rows rather than trusting a contaminated median.
    df["_exp"] = [
        _target_ah(int(cc), _norm_fuel(f) if f else "", int(y)) if pd.notna(cc) else None
        for cc, f, y in zip(df.engine_cc, df.fuel_type, df.year)
    ]
    df["_ratio"] = [
        (a / e) if (e and pd.notna(e)) else None for a, e in zip(df.ah, df._exp)
    ]
    plausible = df[df._ratio.notna() & (df._ratio >= CORE_LO) & (df._ratio <= CORE_HI)]

    medians: dict[tuple[str, str], float] = {}
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for (mk, md), g in plausible.groupby(["make_n", "model_n"]):
        medians[(mk, md)] = float(g["ah"].median())
        counts[(mk, md)] = len(g)

    reasons = Counter()
    changes: list[dict] = []
    audit: list[dict] = []
    examples: list[str] = []

    for r in df.itertuples():
        make_n = str(r.make_n).upper()
        old_ah = int(r.ah)
        new_ah = None
        why = None

        fit = _fitment_override(make_n, _norm_model_key(str(r.model_n)), int(r.year))
        if fit is not None and fit[0]:
            cand = int(round(float(fit[0])))
            if cand != old_ah:
                new_ah, why = cand, "oem_fitment"
        else:
            cc = r.engine_cc
            if pd.notna(cc):
                exp = _target_ah(int(cc), _norm_fuel(r.fuel_type) if r.fuel_type else "",
                                 int(r.year))
                ratio = old_ah / exp if exp else 1.0
                if ratio < RATIO_LO or ratio >= RATIO_HI:
                    new_ah, why = int(exp), "outside_rules_band"
            if new_ah is None and not args.no_median:
                key = (r.make_n, r.model_n)
                med = medians.get(key)
                if med and counts[key] >= MIN_ROWS_FOR_MEDIAN and med > 0:
                    if abs(old_ah - med) / med > MEDIAN_TOLERANCE:
                        new_ah, why = int(round(med)), "model_median_outlier"

        if new_ah is None or new_ah == old_ah:
            continue

        try:
            stocked, code, tech = resolve(new_ah, make_n, r.engine_cc,
                                          r.fuel_type, int(r.year))
        except Exception:
            reasons["resolve_failed"] += 1
            continue

        # The requested figure resolved back to the battery already stored, so
        # there is nothing to correct — only the raw number differed.
        if stocked == old_ah:
            reasons["already_correct_battery"] += 1
            continue
        new_ah = stocked

        reasons[why] += 1
        changes.append({"id": int(r.id), "ah": new_ah, "battery_code": code,
                        "technology": tech})
        audit.append({"mk": str(r.make_n), "md": str(r.model_n), "yr": int(r.year),
                      "old": {"ah": old_ah, "battery_code": r.battery_code,
                              "technology": r.technology},
                      "new": {"ah": new_ah, "battery_code": code,
                              "technology": tech}})
        if len(examples) < 12:
            examples.append(
                f"  {make_n:<12}{str(r.model_n)[:30]:<31}{r.year}  "
                f"{old_ah:>3} -> {new_ah:>3}Ah   {why}")

    print(f"\nrows to correct : {len(changes):,}  ({len(changes)/len(df)*100:.1f}%)")
    for k, n in reasons.most_common():
        print(f"  {k:<24}{n:>6,}")
    if examples:
        print("\nexamples:")
        for e in examples:
            print(e)

    if not args.execute:
        print("\n[DRY RUN] Nothing changed. Re-run with --execute to apply.\n")
        return

    # Staging is disposable and pre-commit, so it needs no audit trail. The
    # live table does: anything written there must be backed up and land in a
    # version + changelog so the admin UI can revert it like any other commit.
    live = args.table != TABLE
    if live:
        now = datetime.now(timezone.utc)
        try:
            res = db_backup.create_backup()
            with engine.begin() as c:
                c.execute(text(
                    "INSERT INTO admin_backup_log (filename,size_bytes,status,"
                    " error_detail,triggered_by,created_at)"
                    " VALUES (:f,:s,'success',NULL,:t,:c)"),
                    {"f": res.filename, "s": res.size_bytes,
                     "t": "fix_staging_ah_outliers.py", "c": now})
            print(f"\n  backup: {res.filename}")
        except db_backup.BackupError as exc:
            print(f"\n  ERROR — backup failed, aborting: {exc}\n")
            return

    with engine.begin() as conn:
        vid = None
        if live:
            vid = str(uuid.uuid4())
            ver = (conn.execute(text(
                "SELECT COALESCE(MAX(version_number),0)"
                " FROM web_battery_validation_versions")).scalar() or 0) + 1
            conn.execute(text(
                "INSERT INTO web_battery_validation_versions"
                " (id,version_number,committed_at,run_id,committed_count,"
                "  removed_count,conflict_count,notes,committed_by,initiated_by)"
                " VALUES (:i,:v,:a,:r,:cc,0,0,:n,:b,:b)"),
                {"i": vid, "v": ver, "a": now,
                 "r": f"ah_outliers_{now:%Y%m%d_%H%M%S}", "cc": len(changes),
                 "n": f"Ah outlier correction: {len(changes)} rows",
                 "b": "fix_staging_ah_outliers.py"})

        for i in range(0, len(changes), 500):
            conn.execute(
                text(f"UPDATE {args.table} SET ah = :ah, battery_code = :battery_code,"
                     f" technology = :technology WHERE id = :id"),
                changes[i:i + 500])

        if live:
            log = [{"v": vid, "mk": c_["mk"], "md": c_["md"], "yr": c_["yr"],
                    "o": json.dumps(c_["old"]), "n": json.dumps(c_["new"])}
                   for c_ in audit]
            for i in range(0, len(log), 500):
                conn.execute(text(
                    "INSERT INTO web_battery_validation_changelog"
                    " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                    " VALUES (:v,:mk,:md,:yr,'update',:o,:n)"), log[i:i + 500])

    print(f"\n  DONE — {len(changes):,} rows corrected in {args.table}"
          + (f" (version {ver})" if live else "") + "\n")


if __name__ == "__main__":
    main()
