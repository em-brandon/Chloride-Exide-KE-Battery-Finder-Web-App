"""
fix_unchecked_ah_via_oem.py
---------------------------
Validate the rows that no plausibility rule can currently see.

THE GAP
-------
Every Ah check in this codebase compares against _target_ah(), which needs
engine_cc. 775 rows in web_battery_validation have no engine_cc — 739 of them
BMW — and it is not recoverable from vehicle_years either (those rows have a
null engine_capacity too). So nothing has ever checked them:

    BMW               739 rows      EICHER             33 rows
    NISSAN DIESEL/UD   22 rows      AUDI                3 rows

Their stored Ah spans 20-120. A 20Ah battery in a BMW is a motorcycle battery
and would not crank the car; it survived every pass purely because no rule
could look at it.

WHY EXIDE, AND WHY A LOOSER MATCH THAN _fitment_override
--------------------------------------------------------
With no engine_cc, Exide's own fitment guide is the ONLY check available.
_fitment_override() needs an exact or >=85 fuzzy match on the full model
string, so Exide's "3 SERIES (E90) 320d" never matches CRSP's
"3 SERIES 320D X DRIVE M-SPORT HI-LINE PACKAGE" and BMW resolves 97 of 894.

Matching a spacing-insensitive leading-token prefix (CRSP writes "A 4", Exide
writes "A4") resolves 536 of the 775. The cost is precision: a short prefix
pulls in every engine variant of that nameplate, so the median it returns is a
NAMEPLATE-level figure, not trim-exact.

That trade is worth taking HERE and nowhere else. These rows have no
alternative check at all, so a real manufacturer median beats an unexamined
scrape. On rows that already pass the rules check, the same trade would
flatten good trim-specific values into variant averages — which is why this
script is scoped strictly to engine_cc IS NULL.

The 239 rows with neither engine_cc nor an Exide match (BMW 206, Eicher 33,
UD 22) are left alone and reported: nothing available can judge them, and
guessing is worse than saying so.

Usage (run from backend/)
-------------------------
    python scripts/fix_unchecked_ah_via_oem.py
    python scripts/fix_unchecked_ah_via_oem.py --execute
"""

from __future__ import annotations

import argparse
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
                     _preferred_tech, _select_batteries)

MAKE_ALIASES = {"MERCEDES": "MERCEDES-BENZ", "LANDROVER": "LAND ROVER"}
MIN_PREFIX_TOKENS = 2
SCRIPT = "fix_unchecked_ah_via_oem.py"


def _compact(s) -> str:
    return "".join(ch for ch in str(s).upper() if ch.isalnum())


def oem_head(model: str, make: str) -> str:
    head = str(model).split("(")[0].strip().upper()
    cm = make.upper().replace(" ", "").replace("-", "")
    seen = 0
    for i, ch in enumerate(head):
        if ch not in (" ", "-"):
            seen += 1
        if seen == len(cm):
            if head[:i + 1].replace(" ", "").replace("-", "") == cm:
                return head[i + 1:].strip() or head
            break
    return head


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    with engine.connect() as conn:
        df = pd.read_sql(
            "SELECT id, make_n, model_n, year, ah, technology, battery_code, fuel_type"
            " FROM web_battery_validation WHERE engine_cc IS NULL", conn)
        oem = pd.read_sql(
            "SELECT upper(trim(make)) mk, model, year_from, year_to, ah"
            " FROM oem_fitment WHERE ah IS NOT NULL", conn)

    print(f"rows with no engine_cc (unchecked by any rule): {len(df):,}")
    if df.empty:
        return 0

    idx: dict[str, list] = defaultdict(list)
    for r in oem.itertuples():
        idx[r.mk].append((_compact(oem_head(r.model, r.mk)), r.year_from, r.year_to, r.ah))

    def oem_ah(mk: str, model: str, year: int):
        cands = idx.get(MAKE_ALIASES.get(mk, mk)) or idx.get(mk) or []
        toks = str(model).upper().split()
        for n in range(len(toks), MIN_PREFIX_TOKENS - 1, -1):
            pre = _compact(" ".join(toks[:n]))
            if len(pre) < 2:
                continue
            hits = [ah for ch, yf, yt, ah in cands
                    if ch.startswith(pre)
                    and (pd.isna(yf) or yf <= year)
                    and (pd.isna(yt) or year <= yt)]
            if hits:
                return float(pd.Series(hits).median())
        return None

    updates, unresolved, examples = [], Counter(), []
    for r in df.itertuples():
        mk = str(r.make_n).upper().strip()
        cand = oem_ah(mk, str(r.model_n), int(r.year))
        if cand is None:
            unresolved[mk] += 1
            continue
        new_ah = int(round(cand))
        if pd.notna(r.ah) and new_ah == int(r.ah):
            continue
        nf = _norm_fuel(r.fuel_type) if r.fuel_type else ""
        try:
            # engine_cc is genuinely unknown here, so _preferred_tech gets 0 and
            # falls to its fuel/luxury/stop-start branches. BMW is in
            # _LUXURY_MAKES, so it correctly resolves to AGM regardless.
            pref = _preferred_tech(0, nf, int(r.year), mk,
                                   _infer_stop_start(mk, int(r.year), nf))
            primary, _ = _select_batteries(new_ah, pref, _make_region(mk))
        except Exception:
            continue
        # Store the Ah of the battery we would actually SELL, not Exide's raw
        # figure. Exide lists the BMW i3 at 21Ah (correct — it is an EV with a
        # small 12V auxiliary battery), but the smallest DIN battery we stock is
        # 43Ah, so _select_batteries() steps up to 43. Storing 21 would print
        # "21Ah" beside a 43Ah battery code in the exported guide, contradicting
        # itself on the page. Keeping ah aligned to the selected battery makes
        # the two columns agree by construction.
        stocked_ah = int(primary["ah"])
        if pd.notna(r.ah) and stocked_ah == int(r.ah):
            continue
        updates.append({"id": int(r.id), "ah": stocked_ah,
                        "battery_code": primary["battery_code"],
                        "technology": primary["technology"]})
        if len(examples) < 10:
            old = int(r.ah) if pd.notna(r.ah) else None
            note = f"  (Exide {new_ah}, stepped to stock)" if stocked_ah != new_ah else ""
            examples.append(f"  {mk:<10}{str(r.model_n)[:34]:<35}{r.year}  "
                            f"{old} -> {stocked_ah}Ah{note}")

    print(f"  resolved via Exide  : {len(updates):,}")
    print(f"  left unresolved     : {sum(unresolved.values()):,}")
    for k, n in unresolved.most_common():
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
            {"i": vid, "v": ver, "a": now, "r": f"unchecked_oem_{now:%Y%m%d_%H%M%S}",
             "cc": len(updates),
             "n": f"Exide re-match for rows with no engine_cc: {len(updates)} rows",
             "b": SCRIPT})
        for i in range(0, len(updates), 500):
            c.execute(text("UPDATE web_battery_validation SET ah=:ah,"
                           " battery_code=:battery_code, technology=:technology"
                           " WHERE id=:id"), updates[i:i + 500])
    print(f"  DONE — version {ver}, {len(updates):,} rows corrected\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
