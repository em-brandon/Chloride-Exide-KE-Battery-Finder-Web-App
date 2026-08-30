"""
fix_ah_kei_and_oem.py
---------------------
Two targeted Ah corrections for web_battery_validation that the existing
plausibility gate cannot catch.

1. KEI-CLASS CAP
----------------
Kei cars are a Japanese legal class capped at 660 cc. They use small batteries
— our NS-region catalogue stocks 35/40/45 in that space — and _target_ah()
returns 45Ah for anything at or under 660 cc.

1,686 rows are kei-class and 716 of them (42%) carry more than 46Ah, up to
80Ah on a Mitsubishi Town Box (658 cc) and a Nissan Roox (659 cc). An 80Ah
battery does not physically belong in a kei car.

Every one of those rows passes the existing 0.5x-2.0x plausibility band,
because 80/45 = 1.78. The band is calibrated for the middle of the range and
is simply too loose where displacement is legally capped, so this adds a hard
ceiling for that class rather than widening a global threshold.

It is NOT a per-make rule. Daihatsu sells the Altis (a Corolla rebadge) at
~80Ah legitimately, so keying on the make would corrupt real data; keying on
engine_cc <= 660 is verifiable per row. The affected rows span eight makes
(Honda 151, Subaru 129, Daihatsu 114, Nissan 103, Mazda 69, Toyota 64,
Mitsubishi 59, Suzuki 26) plus one Fiat — and that Fiat is a wrong engine_cc
rather than a wrong Ah, since Fiat builds no kei cars.

2. SELECTIVE OEM RE-MATCH
-------------------------
_fitment_override() needs an exact or >=85 fuzzy match on the whole model
string, so Exide's "GOLF VII (5G1, BQ1, BE1) 1.4 TSI" never matches CRSP's
"GOLF TSI COMFORTLINE" and only 9.6% of Western rows resolve — while Exide
holds 6,033 VW and 4,931 Volvo rows.

Matching on a spacing-insensitive leading-token prefix (CRSP writes "A 4",
Exide writes "A4") lifts that to 37%. But a short prefix pulls in every engine
variant at once — "A 3" matches 147 Exide entries from 1.4 TFSI to RS3 — so
the median it yields is a NAMEPLATE-level figure, not trim-exact.

Applied everywhere that would overwrite 2,231 reasonable trim-specific scrapes
with variant averages. So it is applied SELECTIVELY: only where the current
value is already implausible. A Santa Fe stored at 50Ah against a real
82-96Ah range is worth replacing; an A3 stored at 70 against a 62-72 range is
not worth flattening.

Order per row: OEM (real manufacturer data) beats the rules figure, and the
kei ceiling is applied last because it is a physical constraint that overrides
both.

Usage (run from backend/)
-------------------------
    python scripts/fix_ah_kei_and_oem.py
    python scripts/fix_ah_kei_and_oem.py --execute
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
from matcher import (_fitment_override, _infer_stop_start, _make_region, _norm_fuel,
                     _norm_model_key,
                     _preferred_tech, _select_batteries, _target_ah)

KEI_CC_MAX = 660
KEI_AH_MAX = 46
RATIO_LO, RATIO_HI = 0.5, 2.0
MIN_PREFIX_TOKENS = 2
MAKE_ALIASES = {"MERCEDES": "MERCEDES-BENZ", "LANDROVER": "LAND ROVER"}
SCRIPT = "fix_ah_kei_and_oem.py"


def _compact(s) -> str:
    return "".join(ch for ch in str(s).upper() if ch.isalnum())


def oem_head(model: str, make: str) -> str:
    """Exide model name minus any leading make name and parenthetical codes."""
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
            "SELECT id, make_n, model_n, year, ah, technology, battery_code,"
            " engine_cc, fuel_type FROM web_battery_validation", conn)
        oem = pd.read_sql(
            "SELECT upper(trim(make)) mk, model, year_from, year_to, ah"
            " FROM oem_fitment WHERE ah IS NOT NULL", conn)

    df["engine_cc"] = pd.to_numeric(df.engine_cc, errors="coerce")
    idx: dict[str, list] = defaultdict(list)
    for r in oem.itertuples():
        idx[r.mk].append((_compact(oem_head(r.model, r.mk)), r.year_from, r.year_to, r.ah))

    def oem_ah(mk: str, model: str, year: int):
        cands = idx.get(MAKE_ALIASES.get(mk, mk)) or idx.get(mk) or []
        if not cands:
            return None
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

    updates, reasons, examples = [], Counter(), []

    for r in df.itertuples():
        if pd.isna(r.ah):
            continue
        mk = str(r.make_n).upper().strip()
        cc = int(r.engine_cc) if pd.notna(r.engine_cc) else 0
        nf = _norm_fuel(r.fuel_type) if r.fuel_type else ""
        exp = _target_ah(cc, nf, int(r.year)) if cc else None
        ratio = (r.ah / exp) if exp else None

        is_kei = 0 < cc <= KEI_CC_MAX
        kei_bad = is_kei and r.ah > KEI_AH_MAX
        band_bad = ratio is not None and (ratio < RATIO_LO or ratio >= RATIO_HI)

        if not (kei_bad or band_bad):
            continue

        # OEM CONFIRMATION VETO — check before treating the row as wrong.
        # _target_ah is unreliable at both extremes: it under-sizes large SUVs
        # (Volvo XC90 -> 55 against Exide's 110) and over-sizes sports cars and
        # hybrids (Nissan GT-R -> 90, Toyota Mirai -> 95, both 45 in Exide's
        # guide). Those rows were already wrongly quarantined once on this
        # dataset. If Exide's guide confirms the stored value, the value is
        # right and the rules estimate is the thing that is wrong.
        exact = _fitment_override(mk, _norm_model_key(str(r.model_n)), int(r.year))
        if exact and exact[0] and int(round(float(exact[0]))) == int(r.ah):
            reasons["oem_confirmed_kept"] += 1
            continue

        new_ah, why = None, None
        cand = oem_ah(mk, str(r.model_n), int(r.year))
        if cand and not (is_kei and cand > KEI_AH_MAX):
            new_ah, why = int(round(cand)), "oem_rematch"
        elif exp:
            new_ah, why = int(exp), "kei_cap" if kei_bad else "rules"

        if new_ah is None:
            continue
        # Physical ceiling wins over both sources.
        if is_kei and new_ah > KEI_AH_MAX:
            new_ah, why = int(exp or 45), "kei_cap"
        if new_ah == r.ah:
            continue

        try:
            pref = _preferred_tech(cc, nf, int(r.year), mk,
                                   _infer_stop_start(mk, int(r.year), nf))
            primary, _ = _select_batteries(new_ah, pref, _make_region(mk))
        except Exception:
            continue

        reasons[why] += 1
        updates.append({"id": int(r.id), "ah": new_ah,
                        "battery_code": primary["battery_code"],
                        "technology": primary["technology"]})
        if len(examples) < 10:
            examples.append(f"  {mk:<12}{str(r.model_n)[:30]:<31}{r.year}  "
                            f"{int(r.ah):>3} -> {new_ah:>3}Ah  {cc or '?'}cc  {why}")

    print(f"rows to correct: {len(updates):,}")
    for k, n in reasons.most_common():
        print(f"  {k:<16}{n:>7,}")
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
            {"i": vid, "v": ver, "a": now, "r": f"kei_oem_{now:%Y%m%d_%H%M%S}",
             "cc": len(updates),
             "n": f"kei-class Ah ceiling + selective OEM re-match: {len(updates)} rows",
             "b": SCRIPT})
        for i in range(0, len(updates), 500):
            c.execute(text("UPDATE web_battery_validation SET ah=:ah,"
                           " battery_code=:battery_code, technology=:technology"
                           " WHERE id=:id"), updates[i:i + 500])
    print(f"  DONE — version {ver}, {len(updates):,} rows corrected\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
