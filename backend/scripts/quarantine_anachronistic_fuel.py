"""
quarantine_anachronistic_fuel.py
--------------------------------
Move rows whose FUEL TYPE could not have existed in their model year out of
web_battery_validation and into web_battery_unmatched.

WHAT THIS CATCHES THAT THE TRIM CHECK DOES NOT
----------------------------------------------
quarantine_anachronistic_years.py keys on trim keywords in the model string
(TSI, MHEV, PHEV...). That misses rows whose model name carries no dateable
marker at all but whose fuel column does:

    DODGE   HORNET GT                2000-2009  HYBRID   (Hornet is 2023+)
    HYUNDAI SANTA FE CALLIGRAPHY     2000-2009  HYBRID   (Calligraphy is 2021+)
    BMW     X 5 X DRIVE 45 E         2000-2006  HYBRID   (xDrive45e is 2019+)

The fuel label on these is RIGHT — they genuinely are hybrids. The year is
wrong: a modern trim inherited its nameplate's whole production span during
enrichment, so a 2023 Dodge Hornet acquired rows back to 2000. Fuel is
therefore a usable proxy for "this trim cannot be this old" on exactly the rows
the model string cannot date.

THE RULE
--------
One date plus a named exemption, rather than a per-make table of dates nobody
can check. Mass-market hybrids arrived with the Prius (1997) and Insight
(1999), and stayed almost exclusively Japanese until around 2010 — Mercedes'
first was 2009, BMW's 2010, Hyundai's 2011, Volvo's 2012. So:

  * HYBRID before HYBRID_FROM_YEAR is anachronistic, EXCEPT for the makes in
    EARLY_HYBRID_MAKES, which were selling them from the late nineties.
  * EV before EV_FROM_YEAR is anachronistic for everyone — the Leaf (2010) and
    Model S (2012) are the start of the volume market, and no make in this
    dataset shipped one earlier.

The floor is set at the point the technology became purchasable rather than at
its earliest prototype, so it only removes years that are impossible, not years
that are merely unusual.

Rows are MOVED, not deleted — web_battery_unmatched keeps them for the manual
research pass, same as every other quarantine in this pipeline.

Usage (run from backend/)
-------------------------
    python scripts/quarantine_anachronistic_fuel.py
    python scripts/quarantine_anachronistic_fuel.py --execute
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
from matcher import _norm_fuel

HYBRID_FROM_YEAR = 2010
EV_FROM_YEAR = 2010
# Makes selling hybrids well before the 2010 mainstream: Prius 1997,
# Insight 1999, RX400h 2005, Altima Hybrid 2007.
EARLY_HYBRID_MAKES = {"TOYOTA", "HONDA", "LEXUS", "NISSAN"}
SCRIPT = "quarantine_anachronistic_fuel.py"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    with engine.connect() as conn:
        df = pd.read_sql("SELECT * FROM web_battery_validation", conn)

    bad = []
    for r in df.itertuples():
        mk = str(r.make_n).upper().strip()
        f = _norm_fuel(r.fuel_type) if r.fuel_type else ""
        yr = int(r.year)
        if f == "HYBRID" and yr < HYBRID_FROM_YEAR and mk not in EARLY_HYBRID_MAKES:
            bad.append((r, f"hybrid_before_{HYBRID_FROM_YEAR}"))
        elif f == "EV" and yr < EV_FROM_YEAR:
            bad.append((r, f"ev_before_{EV_FROM_YEAR}"))

    print(f"rows in web_battery_validation : {len(df):,}")
    print(f"anachronistic fuel/year rows   : {len(bad):,}")
    if not bad:
        print("  nothing to quarantine\n")
        return 0

    per, reasons = Counter(), Counter()
    for r, why in bad:
        per[str(r.make_n).upper()] += 1
        reasons[why] += 1
    for k, n in reasons.most_common():
        print(f"      {k:<26}{n:>6,}")
    print("\n  by make:")
    for m, n in per.most_common():
        tot = int((df.make_n.str.upper() == m).sum())
        print(f"      {m:<16}{n:>5,} of {tot:>5,}  ({n / tot * 100:.0f}%)")
    print("\nexamples:")
    for r, why in bad[:10]:
        print(f"  {str(r.make_n).upper():<10}{str(r.model_n)[:32]:<33}{r.year}  "
              f"{r.fuel_type}  {why}")

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

    batch = f"fuel_anachronism_{now:%Y%m%d_%H%M%S}"
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
             "n": f"Quarantined {len(bad)} rows with impossible fuel/year pairs",
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
                                 "technology": r.technology,
                                 "fuel_type": r.fuel_type}, default=str)}
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
