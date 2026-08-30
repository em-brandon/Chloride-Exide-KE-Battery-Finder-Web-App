"""
quarantine_phantom_years_via_oem.py
-----------------------------------
Remove rows dated years before the model existed, using Exide's own
oem_fitment.year_from as the evidence.

THE DEFECT
----------
Year enrichment attached a nameplate's whole production span to trims that only
appeared late in it, so modern models carry rows reaching back to the year
floor:

    PORSCHE   CAYENNE COUPE      2000-2013     Cayenne Coupe launched 2019
    PEUGEOT   RIFTER             2000-2012     Rifter launched 2018
    MAZDA     CX 8               2004-2011     CX-8 launched 2017
    LANDROVER EVOQUE CONVERTIBLE 2000-2009     Evoque Convertible 2016

Nothing already in the pipeline catches these. The trim-keyword check
(quarantine_anachronistic_years.py) needs a dateable badge in the model string
and "RIFTER" has none; the fuel check (quarantine_anachronistic_fuel.py) needs
a hybrid/EV label and these are ordinary petrol and diesel cars.

THE EVIDENCE, AND WHY ONLY IN ONE DIRECTION
-------------------------------------------
oem_fitment carries real year_from/year_to per catalogue entry. A row dated
before the earliest year Exide lists for that model is suspect, because Exide
cannot sell a battery for a car that does not exist yet.

The reverse test — flagging rows AFTER year_to as "model discontinued" — was
measured and REJECTED. It fires on 811 rows including Hino Dutro and Toyota
Townace, both still in production: a stale catalogue entry that stops at 2001
means Exide has not revised that entry, not that the truck died. The asymmetry
is real, so only the early side is used.

MARGIN
------
Exide is a sales catalogue, not a production record — it need not list a
model's first year or two. A row is therefore only quarantined when it sits
more than MARGIN_YEARS before Exide's earliest listing, so ordinary catalogue
lag is not mistaken for a phantom year. Verified at this margin the affected
set contains no long-running mainstream nameplate (no Toyota, Nissan or Honda
false positives) — every model caught is one that genuinely launched after the
years attached to it.

Models Exide does not cover at all cannot be tested this way; EXPLICIT_FLOORS
carries the handful known to be modern that the catalogue misses.

Rows are MOVED to web_battery_unmatched, not deleted.

Usage (run from backend/)
-------------------------
    python scripts/quarantine_phantom_years_via_oem.py
    python scripts/quarantine_phantom_years_via_oem.py --execute
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
from scripts.apply_oem_to_staging import MAKE_ALIASES, _compact, oem_head

MARGIN_YEARS = 5
# (make, model-name prefix) -> first year that model existed. For nameplates
# Exide's catalogue does not carry, so the year_from test cannot see them.
EXPLICIT_FLOORS: dict[tuple[str, str], int] = {
    ("DODGE", "HORNET"): 2022,
}
SCRIPT = "quarantine_phantom_years_via_oem.py"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    with engine.connect() as conn:
        w = pd.read_sql("SELECT * FROM web_battery_validation", conn)
        oem = pd.read_sql(
            "SELECT upper(trim(make)) mk, model, year_from FROM oem_fitment"
            " WHERE year_from IS NOT NULL", conn)

    idx: dict[str, list] = defaultdict(list)
    for r in oem.itertuples():
        idx[r.mk].append((_compact(oem_head(r.model, r.mk)), r.year_from))

    def exide_first(mk: str, model: str):
        cands = idx.get(MAKE_ALIASES.get(mk, mk)) or idx.get(mk) or []
        toks = str(model).upper().split()
        for n in range(len(toks), 0, -1):
            pre = _compact(" ".join(toks[:n]))
            if len(pre) < (4 if n == 1 else 2):
                continue
            hits = [yf for ch, yf in cands if ch.startswith(pre)]
            if hits:
                return min(hits)
        return None

    def explicit_floor(mk: str, model: str):
        m = str(model).upper()
        for (fmk, pre), yr in EXPLICIT_FLOORS.items():
            if mk == fmk and m.startswith(pre):
                return yr
        return None

    bad, reasons = [], Counter()
    for r in w.itertuples():
        mk = str(r.make_n).upper().strip()
        yr = int(r.year)
        floor = explicit_floor(mk, r.model_n)
        if floor is not None:
            if yr < floor:
                bad.append((r, "before_known_launch"))
                reasons["before_known_launch"] += 1
            continue
        ef = exide_first(mk, str(r.model_n))
        if ef is not None and yr < ef - MARGIN_YEARS:
            bad.append((r, "predates_oem_listing"))
            reasons["predates_oem_listing"] += 1

    print(f"rows in web_battery_validation : {len(w):,}")
    print(f"phantom-year rows              : {len(bad):,}")
    if not bad:
        print("  none found\n")
        return 0
    for k, n in reasons.most_common():
        print(f"      {k:<24}{n:>6,}")

    per = Counter(str(r.make_n).upper() for r, _ in bad)
    print("\n  by make:")
    for m, n in per.most_common():
        tot = int((w.make_n.str.upper() == m).sum())
        print(f"      {m:<14}{n:>5,} of {tot:>5,}  ({n / tot * 100:.0f}%)")

    seen, ex = set(), []
    for r, why in bad:
        k = (str(r.make_n).upper(), str(r.model_n))
        if k in seen:
            continue
        seen.add(k)
        if len(ex) < 12:
            ex.append(f"  {k[0]:<10}{k[1][:38]:<39}{r.year}  {why}")
    print("\nexamples (one per model):")
    for e in ex:
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

    batch = f"phantom_years_{now:%Y%m%d_%H%M%S}"
    vid = str(uuid.uuid4())
    with engine.begin() as c:
        ver = (c.execute(text("SELECT COALESCE(MAX(version_number),0)"
                              " FROM web_battery_validation_versions")).scalar() or 0) + 1
        c.execute(text(
            "INSERT INTO web_battery_validation_versions"
            " (id,version_number,committed_at,run_id,committed_count,removed_count,"
            "  conflict_count,notes,committed_by,initiated_by)"
            " VALUES (:i,:v,:a,:r,0,:rm,0,:n,:b,:b)"),
            {"i": vid, "v": ver, "a": now, "r": batch, "rm": len(bad),
             "n": f"Quarantined {len(bad)} rows dated before the model existed",
             "b": SCRIPT})

        rows = [{"mk": r.make_n, "md": r.model_n, "yr": int(r.year),
                 "ah": int(r.ah) if pd.notna(r.ah) else None,
                 "cc": int(r.engine_cc) if pd.notna(r.engine_cc) else None,
                 "ft": r.fuel_type, "bc": r.battery_code, "tech": r.technology,
                 "why": why, "at": now, "b": batch} for r, why in bad]
        for i in range(0, len(rows), 500):
            c.execute(text(
                "INSERT INTO web_battery_unmatched (make_n,model_n,year,ah,expected_ah,"
                " engine_cc,fuel_type,battery_code,technology,source_table,reason,"
                " moved_at,batch_id) VALUES (:mk,:md,:yr,:ah,NULL,:cc,:ft,:bc,:tech,"
                " 'web_battery_validation',:why,:at,:b)"), rows[i:i + 500])

        log = [{"v": vid, "mk": r.make_n, "md": r.model_n, "yr": int(r.year),
                "o": json.dumps({"battery_code": r.battery_code,
                                 "ah": int(r.ah) if pd.notna(r.ah) else None,
                                 "technology": r.technology}, default=str)}
               for r, _ in bad]
        for i in range(0, len(log), 500):
            c.execute(text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                " VALUES (:v,:mk,:md,:yr,'remove',:o,NULL)"), log[i:i + 500])

        ids = [int(r.id) for r, _ in bad]
        for i in range(0, len(ids), 500):
            c.execute(text("DELETE FROM web_battery_validation WHERE id = ANY(:ids)"),
                      {"ids": ids[i:i + 500]})

    print(f"  DONE — version {ver}, {len(bad):,} rows quarantined\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
