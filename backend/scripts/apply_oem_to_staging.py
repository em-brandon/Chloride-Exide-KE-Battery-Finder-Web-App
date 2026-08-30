"""
apply_oem_to_staging.py
-----------------------
Re-resolve staged Ah values from Exide's own fitment guide before commit.

WHY THIS MUST RUN BEFORE fix_staging_ah_outliers.py
---------------------------------------------------
fix_staging_ah_outliers.py consults oem_fitment through _fitment_override(),
which needs an exact or >=85 fuzzy match on the whole model string. European
naming defeats it: Exide writes "C-CLASS (W203) C 180 (203.035)" where CRSP
writes "C CLASS C 180 LAUREUS EDITION". When that lookup misses, the script
falls through to its rules tier — and _target_ah() returns 45Ah for a 1500cc
Mercedes, so it "corrected" real 95Ah C-Class rows down to 45Ah. Exide lists
that car at 60-100Ah. The scrape was right and the rule was wrong.

Matching a spacing-insensitive leading-token prefix (CRSP "A 4" vs Exide "A4")
resolves what _fitment_override cannot, so running this FIRST means the rules
tier only ever sees rows Exide genuinely cannot speak to.

_target_ah() is unreliable at both ends of the range — it under-sizes European
saloons, large SUVs and commercials, and over-sizes hybrids, EVs and sports
cars (Prius, BMW i3, Nissan GT-R). Every time it disagreed with Exide during
this dataset's cleanup, Exide was right. Treat the guide as authoritative and
the rules as a fallback, never the reverse.

PRECISION CAVEAT
----------------
A short prefix matches every engine variant of a nameplate at once ("A 3" hits
147 Exide entries from 1.4 TFSI to RS3), so the median returned is a
NAMEPLATE-level figure rather than trim-exact. That is a good trade against an
unverified scrape, and a poor one against a scrape that already agrees with the
rules — which is why the default only rewrites rows the rules consider
implausible. Pass --all to rewrite every row Exide can resolve.

The stored Ah is the Ah of the battery actually selected, not Exide's raw
number: Exide lists the BMW i3 at 21Ah but the smallest DIN battery stocked is
43Ah, and printing "21Ah" beside a 43Ah battery code contradicts itself on the
page.

Usage (run from backend/)
-------------------------
    python scripts/apply_oem_to_staging.py
    python scripts/apply_oem_to_staging.py --execute
    python scripts/apply_oem_to_staging.py --execute --all
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
from sqlalchemy import text

from db import engine
from matcher import (_infer_stop_start, _make_region, _norm_fuel,
                     _preferred_tech, _select_batteries, _target_ah)

MAKE_ALIASES = {"MERCEDES": "MERCEDES-BENZ", "LANDROVER": "LAND ROVER"}
MIN_PREFIX_TOKENS = 2
RATIO_LO, RATIO_HI = 0.5, 2.0
KEI_CC_MAX, KEI_AH_MAX = 660, 46


def _compact(s) -> str:
    return "".join(ch for ch in str(s).upper() if ch.isalnum())


# How the OEM guide spells a make at the START of its model strings, where that
# differs from the make column. Without these the make prefix is not recognised
# and so never stripped, and the entry keeps a leading token our model names do
# not have — so nothing ever matches.
#
#   VOLKSWAGEN     every one of 6,151 entries begins "VW"
#   MERCEDES-BENZ  5,169 entries begin "MERCEDEZ-BENZ" — a misspelling in the
#                  source data, kept here rather than corrected in the table
#                  because the guide is reference data we do not edit
#
# Both were found by measuring: the guide holds thousands of Volkswagen entries
# while our matcher reported zero Volkswagen coverage, which is not a plausible
# gap in a supplier's own catalogue.
_MAKE_PREFIX_SPELLINGS: dict[str, tuple[str, ...]] = {
    "VOLKSWAGEN": ("VOLKSWAGEN", "VW"),
    "MERCEDES-BENZ": ("MERCEDES-BENZ", "MERCEDEZ-BENZ", "MERCEDES", "MERCEDEZ"),
    "MERCEDES": ("MERCEDES-BENZ", "MERCEDEZ-BENZ", "MERCEDES", "MERCEDEZ"),
}


# Make prefixes that appear on OUR model names but not on the guide's. CRSP
# records every Jeep as "CHRYSLER <model>", while the guide simply says
# "CHEROKEE", so our longest-prefix search starts from a token the guide has
# never heard of and every Jeep falls through unmatched.
_OUR_MODEL_PREFIXES: dict[str, tuple[str, ...]] = {
    "JEEP": ("CHRYSLER",),
}


def our_model_tokens(make: str, model: str) -> list[str]:
    """Our model name as tokens, with any spurious leading make word removed."""
    toks = str(model).upper().split()
    for pre in _OUR_MODEL_PREFIXES.get(make.upper().strip(), ()):
        if toks and toks[0] == pre and len(toks) > 1:
            toks = toks[1:]
            break
    return toks


def oem_prefixes(make: str, model: str) -> list[tuple[str, bool]]:
    """Candidate keys for one of our models, longest first.

    Each item is (compacted key, exact_only). A single short token is returned
    with exact_only=True: Lexus names its cars CT, ES, GS and RX, so a 4-char
    floor on one-token keys — needed to stop the "A" of "A 3" matching half a
    catalogue — silently excluded every Lexus. Requiring an exact match on the
    guide's own leading token instead admits "CT" against "CT" while still
    refusing "A" against "A3", which is the distinction the floor was reaching
    for in the first place.
    """
    toks = our_model_tokens(make, model)
    out: list[tuple[str, bool]] = []
    for n in range(len(toks), 0, -1):
        key = _compact(" ".join(toks[:n]))
        if len(key) < 2:
            continue
        out.append((key, n == 1 and len(key) < 4))
    return out


def oem_head(model: str, make: str) -> str:
    """Exide model name minus a leading make name and parenthetical codes."""
    head = str(model).split("(")[0].strip().upper()
    mk = make.upper().strip()
    for spelling in _MAKE_PREFIX_SPELLINGS.get(mk, (mk,)):
        cm = spelling.replace(" ", "").replace("-", "")
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
    p.add_argument("--all", action="store_true",
                   help="Rewrite every Exide-resolvable row, not just implausible ones.")
    p.add_argument("--table", default="web_battery_staging")
    args = p.parse_args()

    with engine.connect() as conn:
        st = pd.read_sql(
            f"SELECT id, make_n, model_n, year, ah, engine_cc, fuel_type"
            f" FROM {args.table}", conn)
        oem = pd.read_sql(
            "SELECT upper(trim(make)) mk, model, year_from, year_to, ah"
            " FROM oem_fitment WHERE ah IS NOT NULL", conn)

    print(f"rows in {args.table}: {len(st):,}")
    if st.empty:
        return 0
    st["engine_cc"] = pd.to_numeric(st.engine_cc, errors="coerce")

    idx: dict[str, list] = defaultdict(list)
    for r in oem.itertuples():
        idx[r.mk].append((_compact(oem_head(r.model, r.mk)), r.year_from, r.year_to, r.ah))

    def oem_ah(mk: str, model: str, year: int):
        cands = idx.get(MAKE_ALIASES.get(mk, mk)) or idx.get(mk) or []

        # Keys come from oem_prefixes(), longest first, so this shares one
        # definition of "does our model name match theirs" with the verifier and
        # the workbook export. They previously each carried their own copy and
        # drifted apart — the export reported Volkswagen as having no
        # manufacturer backing at all while the guide held 6,151 VW entries.
        for key, exact_only in oem_prefixes(mk, model):
            hits = [ah for ch, yf, yt, ah in cands
                    if ((ch == key) if exact_only else ch.startswith(key))
                    and (pd.isna(yf) or yf <= year) and (pd.isna(yt) or year <= yt)]
            if hits:
                return float(pd.Series(hits).median())
        return None

    updates, reasons, examples = [], Counter(), []
    for r in st.itertuples():
        if pd.isna(r.ah):
            continue
        mk = str(r.make_n).upper().strip()
        cc = int(r.engine_cc) if pd.notna(r.engine_cc) else 0
        nf = _norm_fuel(r.fuel_type) if r.fuel_type else ""
        exp = _target_ah(cc, nf, int(r.year)) if cc else None
        ratio = (r.ah / exp) if exp else None
        implausible = (
            (ratio is not None and (ratio < RATIO_LO or ratio >= RATIO_HI))
            or (0 < cc <= KEI_CC_MAX and r.ah > KEI_AH_MAX)
            or exp is None          # nothing else can judge it
        )
        if not (args.all or implausible):
            continue

        cand = oem_ah(mk, str(r.model_n), int(r.year))
        if cand is None:
            reasons["no_oem_match"] += 1
            continue
        try:
            pref = _preferred_tech(cc, nf, int(r.year), mk,
                                   _infer_stop_start(mk, int(r.year), nf))
            primary, _ = _select_batteries(int(round(cand)), pref, _make_region(mk))
        except Exception:
            continue
        stocked = int(primary["ah"])
        if stocked == int(r.ah):
            continue
        reasons["oem_applied"] += 1
        updates.append({"id": int(r.id), "ah": stocked,
                        "battery_code": primary["battery_code"],
                        "technology": primary["technology"]})
        if len(examples) < 10:
            note = f" (Exide {cand:.0f}, stepped to stock)" if stocked != int(round(cand)) else ""
            examples.append(f"  {mk:<11}{str(r.model_n)[:32]:<33}{r.year}  "
                            f"{int(r.ah):>3} -> {stocked:>3}Ah{note}")

    print(f"  rows to correct : {len(updates):,}")
    for k, n in reasons.most_common():
        print(f"      {k:<18}{n:>7,}")
    if examples:
        print("\nexamples:")
        for e in examples:
            print(e)

    if not args.execute:
        print("\n[DRY RUN] Nothing changed. Re-run with --execute to apply.\n")
        return 0

    with engine.begin() as conn:
        for i in range(0, len(updates), 500):
            conn.execute(text(
                f"UPDATE {args.table} SET ah=:ah, battery_code=:battery_code,"
                f" technology=:technology WHERE id=:id"), updates[i:i + 500])
    print(f"\n  DONE — {len(updates):,} rows re-resolved from Exide in {args.table}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
