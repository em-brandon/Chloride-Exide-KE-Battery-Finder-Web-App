"""
verify_web_validation_quality.py
--------------------------------
Report-readiness gate for web_battery_staging (or web_battery_validation).

Run this BEFORE committing staging to master and before exporting anything a
client sees. Every check below corresponds to a defect this dataset has
actually shipped at some point:

  1. battery_code resolves          — a code not in battery_specs is unsellable.
  2. technology matches the code    — the two columns contradicting each other
                                      on ~40% of rows is the defect the client
                                      originally flagged in the fitment guide.
  3. region matches the make        — NS (Japanese/Korean/Chinese) vs DIN
                                      (European/American). 490 rows once held a
                                      DIN code on an NS make.
  4. Ah is plausible                — scraped Ah is the least reliable column;
                                      a kei truck at 200Ah or a heavy truck at
                                      26Ah is what gets spotted in a review.
  5. year floor                     — no pre-2000 rows.
  6. no ghost vehicles              — every (make, model, year) still exists in
                                      vehicle_years after the year cleanup.
  7. no duplicate keys              — one row per (make, model, year).
  8. anachronistic trims            — HYBRID/E:HEV/TFSI etc. dated before that
                                      technology existed.
  9. coverage                       — rows per make, so a silently-empty make
                                      is visible rather than assumed fine.

Exit code is 1 if any FAIL-level check trips, so this can gate a pipeline.

Usage (run from backend/)
-------------------------
    python scripts/verify_web_validation_quality.py
    python scripts/verify_web_validation_quality.py --table web_battery_validation
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
from sqlalchemy import text

from db import engine
from matcher import _fitment_override, _make_region, _norm_fuel, _target_ah

# Trim keyword -> first year that technology existed. Mirrors
# scripts/quarantine_anachronistic_years.py.
ANACHRONISMS = {
    "HYBRID": 1997, "E:HEV": 2018, "PHEV": 2010, "PHV": 2012, "MHEV": 2016,
    "TFSI": 2004, "TSI": 2005, "SKYACTIV": 2011, "BLUETEC": 2006,
    "E-POWER": 2016, "EYESIGHT": 2010,
}

YEAR_FLOOR = 2000
AH_LO_RATIO, AH_HI_RATIO = 0.5, 2.0

_results: list[tuple[str, str, str]] = []

_OEM_ALIASES = {"MERCEDES": "MERCEDES-BENZ", "LANDROVER": "LAND ROVER"}


def _oem_compact(s) -> str:
    return "".join(ch for ch in str(s).upper() if ch.isalnum())


def _oem_head(model: str, make: str) -> str:
    """Exide model name minus a leading make name and parenthetical codes."""
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


def check(level: str, name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else level
    _results.append((status, name, detail))
    mark = {"PASS": "  ok  ", "FAIL": " FAIL ", "WARN": " warn "}[status]
    print(f"[{mark}] {name}" + (f"  — {detail}" if detail else ""))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--table", default="web_battery_staging")
    args = p.parse_args()
    t = args.table

    with engine.connect() as conn:
        df = pd.read_sql(f"SELECT * FROM {t}", conn)
        specs = pd.read_sql(
            "SELECT battery_code, technology, model_key FROM battery_specs"
            " WHERE deleted_at IS NULL", conn)
        vy = pd.read_sql(
            "SELECT DISTINCT upper(trim(make)) mk, upper(trim(model)) md, year"
            " FROM vehicle_years", conn)
        oem_rows = pd.read_sql(
            "SELECT upper(trim(make)) mk, model, year_from, year_to, ah"
            " FROM oem_fitment WHERE ah IS NOT NULL", conn)

    print(f"\n{'=' * 74}\n  REPORT-READINESS CHECK — {t}\n{'=' * 74}")
    print(f"\nrows: {len(df):,}   makes: {df.make_n.str.upper().nunique()}   "
          f"years: {int(df.year.min())}-{int(df.year.max())}\n")
    if df.empty:
        print("  table is empty — nothing to verify\n")
        return 1

    spec_tech = dict(zip(specs.battery_code, specs.technology))
    spec_key = dict(zip(specs.battery_code, specs.model_key))

    # 1 — battery_code resolves
    unresolved = df[~df.battery_code.isin(spec_tech.keys())]
    check("FAIL", "battery_code resolves in battery_specs", unresolved.empty,
          f"{len(unresolved)} unresolved" if len(unresolved) else "all resolve")

    # 2 — technology matches the resolved battery
    res = df[df.battery_code.isin(spec_tech.keys())].copy()
    res["real_tech"] = res.battery_code.map(spec_tech)
    mismatch = res[res.technology.str.upper() != res.real_tech.str.upper()]
    check("FAIL", "technology matches battery_code", mismatch.empty,
          f"{len(mismatch)} contradict" if len(mismatch) else "all consistent")

    # 3 — region matches the make
    def code_region(code: str) -> str:
        from matcher import _battery_region
        return _battery_region(str(spec_key.get(code, "")))
    res["want"] = [_make_region(str(m).upper()) for m in res.make_n]
    res["got"] = [code_region(c) for c in res.battery_code]
    wrong_region = res[res.want != res.got]
    check("FAIL", "battery region matches make (NS/DIN)", wrong_region.empty,
          f"{len(wrong_region)} wrong region" if len(wrong_region)
          else "all correct")

    # 4 — Ah plausibility
    d = df.copy()
    d["engine_cc"] = pd.to_numeric(d.engine_cc, errors="coerce")
    d = d.dropna(subset=["engine_cc", "ah"])
    d["exp"] = [_target_ah(int(cc), _norm_fuel(f) if f else "", int(y))
                for cc, f, y in zip(d.engine_cc, d.fuel_type, d.year)]
    d["r"] = d.ah / d.exp
    extreme = d[(d.r < AH_LO_RATIO) | (d.r >= AH_HI_RATIO)]
    plaus = ((d.r >= 0.75) & (d.r <= 1.35)).mean() * 100

    # A row backed by Exide's own fitment guide is NOT an error just because it
    # disagrees with _target_ah — the OEM guide is the better source, and this
    # check's own baseline is the weaker one. Every "extreme" row on the first
    # Western run (Audi Q7/Q5 110Ah, Volvo XC90 110Ah, Kia Sportage 95Ah)
    # matched Exide exactly against a rules estimate of 45-55, i.e. _target_ah
    # under-sizes large SUVs. Flagging real manufacturer data as a defect would
    # push someone to "fix" correct rows into wrong ones.
    from matcher import _norm_model_key as _nmk

    # The exemption must use the SAME matching the correction scripts use.
    # _fitment_override alone needs an exact/>=85 fuzzy hit on the whole model
    # string, which fails for most European naming — Exide writes
    # "C-CLASS (W203) C 180 (203.035)" where CRSP writes
    # "C CLASS C 180 LAUREUS EDITION". With only that check, all 10 extreme
    # Mercedes E-Class rows were reported as defects even though Exide lists
    # them at 96Ah against a rules estimate of 45. Falling back to the
    # spacing-insensitive prefix match (see fix_unchecked_ah_via_oem.py) keeps
    # verifier and corrector agreeing about what counts as OEM-backed.
    oem_idx: dict[str, list] = {}
    for r in oem_rows.itertuples():
        oem_idx.setdefault(r.mk, []).append(
            (_oem_compact(_oem_head(r.model, r.mk)), r.year_from, r.year_to, r.ah))

    def _oem_prefix_ah(mk: str, model: str, year: int):
        cands = oem_idx.get(_OEM_ALIASES.get(mk, mk)) or oem_idx.get(mk) or []
        toks = str(model).upper().split()
        for n in range(len(toks), 1, -1):
            pre = _oem_compact(" ".join(toks[:n]))
            if len(pre) < 2:
                continue
            hits = [ah for ch, yf, yt, ah in cands
                    if ch.startswith(pre)
                    and (pd.isna(yf) or yf <= year) and (pd.isna(yt) or year <= yt)]
            if hits:
                return float(pd.Series(hits).median())
        return None

    # Exide's figures are real manufacturer values (82, 96, 67) and are often
    # not sizes we stock, so `ah` holds the SELECTED battery's rating instead
    # (see align_ah_to_selected_battery.py). Exact equality against Exide's raw
    # number therefore no longer holds for a correctly-sourced row — an 82Ah
    # Exide entry legitimately stores 80. Allow the step to the nearest stocked
    # size, which is what OEM_STEP_TOLERANCE covers; anything beyond that is a
    # genuine disagreement and stays flagged.
    OEM_STEP_TOLERANCE = 0.10

    def _within(a: float, b: float) -> bool:
        return bool(b) and abs(a - b) / b <= OEM_STEP_TOLERANCE

    oem_backed = []
    for r in extreme.itertuples():
        fit = _fitment_override(str(r.make_n).upper(), _nmk(str(r.model_n)), int(r.year))
        ok = bool(fit and fit[0] and _within(float(r.ah), float(fit[0])))
        if not ok:
            pref_ah = _oem_prefix_ah(str(r.make_n).upper(), str(r.model_n), int(r.year))
            # within 10% of Exide's figure counts as confirmed — the prefix
            # match is nameplate-level, so exact equality is too strict.
            ok = bool(pref_ah and abs(pref_ah - r.ah) / pref_ah <= 0.10)
        oem_backed.append(ok)
    unexplained = extreme[[not b for b in oem_backed]]
    n_oem = sum(oem_backed)
    check("FAIL", "no unexplained extreme Ah (outside 0.5x-2x of rules)",
          unexplained.empty,
          f"{len(unexplained)} extreme" if len(unexplained)
          else f"{plaus:.1f}% in the tight plausible band"
               + (f"; {n_oem} extreme but OEM-confirmed" if n_oem else ""))

    # 5 — year floor
    old = df[df.year < YEAR_FLOOR]
    check("FAIL", f"no rows before {YEAR_FLOOR}", old.empty,
          f"{len(old)} rows" if len(old) else f"earliest {int(df.year.min())}")

    # 6 — no ghost vehicles
    #
    # Compare on _norm_model_key, the same canonical form the matcher uses, not
    # on raw upper(trim()). CRSP and the validation table disagree about
    # spacing and hyphens around alphanumerics ("CX-5" / "CX 5" / "CX5"), so a
    # literal compare reported 10,762 of 21,046 rows as missing vehicles when
    # the true count on the same data was zero. A check that flags half the
    # table as broken teaches everyone to ignore it.
    vy_keys = {(mk, _nmk(str(md)), yr) for mk, md, yr in zip(vy.mk, vy.md, vy.year)}
    ghost = [r for r in df.itertuples()
             if (str(r.make_n).upper().strip(),
                 _nmk(str(r.model_n)), int(r.year)) not in vy_keys]
    check("WARN", "every vehicle exists in vehicle_years", not ghost,
          f"{len(ghost)} not found (may be model-name formatting)"
          if ghost else "all present")

    # 7 — duplicate keys
    dup = df.duplicated(subset=["make_n", "model_n", "year"]).sum()
    check("FAIL", "no duplicate (make, model, year)", dup == 0,
          f"{dup} duplicates" if dup else "unique")

    # 8 — anachronistic trims
    bad_trim = []
    up = df.model_n.astype(str).str.upper()
    for kw, first in ANACHRONISMS.items():
        hit = df[up.str.contains(kw, regex=False, na=False) & (df.year < first)]
        if len(hit):
            bad_trim.append(f"{kw}<{first}: {len(hit)}")
    check("FAIL", "no anachronistic trim/year pairs", not bad_trim,
          "; ".join(bad_trim) if bad_trim else "none")

    # 9 — coverage
    per = df.groupby(df.make_n.str.upper()).size().sort_values(ascending=False)
    check("WARN", "per-make coverage", True,
          f"{len(per)} makes, smallest {per.index[-1]}={per.iloc[-1]}")
    print()
    for mk, n in per.items():
        print(f"    {mk:<20}{n:>6,}")

    fails = [r for r in _results if r[0] == "FAIL"]
    warns = [r for r in _results if r[0] == "WARN"]
    print(f"\n{'=' * 74}")
    if fails:
        print(f"  NOT READY — {len(fails)} check(s) failed")
        for _, n, d_ in fails:
            print(f"    FAIL  {n}  ({d_})")
    else:
        print(f"  READY — all blocking checks passed"
              + (f", {len(warns)} warning(s)" if warns else ""))
    print(f"{'=' * 74}\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
