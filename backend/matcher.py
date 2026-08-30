"""
Battery recommendation rule engine.

Data sources (all Postgres tables, loaded once at startup into an in-memory
pandas cache — see the @lru_cache loaders below)
------------------------------------------------------------------------
vehicle_years           : make, model, year, engine_capacity, fuel
vehicle_years_exide     : make, model, year, engine_capacity, fuel — Exide
                          fitment-guide vehicles (unioned with vehicle_years
                          by _vehicles(), never written to vehicle_years itself)
battery_specs           : Battery Code, Model Key, Ah, CCA (A EN), Technology
dial_battery_inference  : real-world call-centre sales data (highest-frequency
                          battery code sold per make/model)
web_battery_validation  : internet-sourced fitment data, populated offline by
                          pipelines/web_battery_validate.py
oem_fitment             : Exide's official global fitment guide — Ah/technology
                          per make/model/year-range, populated offline by
                          pipelines/exide_fitment_clean.py

Matching layers (checked in order in `recommend()`; first hit wins)
---------------------------------------------------------------------
0a. Web validation — year-specific internet-sourced fitment      → confidence 75–90
0b. Inference      — real-world call-centre sales data            → confidence 80–95
1.  Exact          — make + fuzzy model (≥90) + exact year        → confidence 100
2.  Soft           — make + fuzzy model (≥60) + year within ±3    → confidence 60–89
3.  Rule           — engine_cc + normalised fuel_type → Ah bracket → confidence 40

Layers 0a/0b take priority over 1–3 because they reflect actual fitment
outcomes (real sales, internet-verified) rather than a rule-of-thumb Ah
estimate — but they only fire when a matching row exists in their source
table, so most searches still fall through to layers 1–3.

oem_fitment is not a competing layer — it doesn't affect which layer above
matches the vehicle or the resulting confidence. Instead, once any layer
resolves a matched (make, model, year), oem_fitment is checked for that same
vehicle and, if found, its Ah REPLACES whatever that layer would otherwise
have used — even a 0a/0b confirmed-battery-code Ah — since it's Exide's own
official spec sheet. The response's `ah_source` field records which path
actually supplied the Ah: "oem_fitment", "battery_code" (0a/0b's normal
path), or "cc_bracket_estimate" (1/2/3's normal path).

oem_fitment's technology column is NOT applied to preferred_tech — many of
its values are Exide product-tier names (PREMIUM, CLASSIC, START PRO, ...)
rather than actual chemistry, and even where it is a real chemistry value,
technology preference must keep following this app's own luxury-make/
stop-start rules (luxury makes always prefer AGM, falling back to EFB if
AGM isn't stocked at the target Ah; stop-start vehicles prefer EFB/AGM per
_preferred_tech()) rather than deferring to Exide's per-vehicle tech, which
doesn't know about local stock or this app's brand-tier policy.

A single make/model/year-range commonly has several oem_fitment rows —
Exide lists multiple battery tiers for the same trim (e.g. a base 50Ah/MF
option alongside 55Ah/EFB and 60Ah/EFB upgrades), which is not duplicate
data (see OemFitment's unique constraint). _fitment_override() picks among
tied tiers by preferring whichever one's technology matches the
already-decided preferred_tech, falling back to the highest Ah overall
when none match — see [OEM Fitment Override](#oem-fitment-override) in
README.md.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional, cast

import pandas as pd
from rapidfuzz import process, fuzz


def _fuzzy_model_score(query: str, choices: list[str]) -> tuple[str, float] | None:
    """
    Ranked multi-scorer model matching.

    Tries, in order:
    1) partial_ratio     — catches prefix inputs ("COROLLA" → "COROLLA AXIO G")
    2) token_set_ratio   — catches variant-token inputs ("MARCH ACTIVE" → "MARCH G")
    3) WRatio fallback   — preserves previous behaviour

    Returns (best_match, best_score) or None if no match passes thresholds.

    Notes:
    - Guard partial_ratio with len(query) >= 4 to reduce false positives on very
      short inputs (e.g. "C" matching "C CLASS").
    """
    if not query or not isinstance(query, str) or not choices:
        return None

    q = query.strip().upper()
    if not q:
        return None

    if len(q) >= 4:
        p_result = process.extractOne(q, choices, scorer=fuzz.partial_ratio)
        if p_result and p_result[1] >= 80:
            return p_result[0], float(p_result[1])

    t_result = process.extractOne(q, choices, scorer=fuzz.token_set_ratio)
    if t_result and t_result[1] >= 72:
        return t_result[0], float(t_result[1])

    w_result = process.extractOne(q, choices, scorer=fuzz.WRatio)
    if w_result and w_result[1] >= 60:
        return w_result[0], float(w_result[1])

    return None


def _fuzzy_model_score_for_year(
    query: str,
    make_df: pd.DataFrame,
    year: int,
    years_by_model: dict[str, tuple[int, ...]] | None = None,
) -> tuple[str, float] | None:
    """Like `_fuzzy_model_score`, but prefers candidates that exist near `year`.

    This avoids token-set tie pitfalls where many trims score 100 against a short
    base model name (e.g. "FIT" matches many "FIT ..." trims), by selecting a
    candidate model that has an exact (or ±3-year) row in `vehicle_years.csv`.

    `years_by_model` (from `_make_index()`) lets the per-candidate year check
    below use a dict/tuple lookup instead of re-filtering `make_df` with a
    pandas boolean mask for every one of the ~60-80 candidates a scorer call
    can return. Falls back to filtering `make_df` directly when not supplied.
    """
    if make_df is None or make_df.empty:
        return None

    model_choices = (
        list(years_by_model.keys())
        if years_by_model is not None
        else make_df["model_n"].dropna().unique().tolist()
    )
    if not model_choices:
        return None

    q = (query or "").strip().upper()
    if not q:
        return None

    q_first = q.split()[0] if q.split() else ""

    def _starts_with_query(candidate: str) -> bool:
        cand = (candidate or "").strip().upper()
        if not cand:
            return False
        if cand.startswith(q):
            return True
        if q_first and (cand.startswith(q_first) or cand.replace("-", " ").startswith(q_first)):
            return True
        return False

    def _cand_years(cand_model_n: str) -> tuple[int, ...]:
        if years_by_model is not None:
            return years_by_model.get(cand_model_n, ())
        cand_df = make_df[make_df["model_n"] == cand_model_n]
        return tuple(sorted(cand_df["year"].dropna().unique().astype(int).tolist()))

    def _pick_best(results: list[tuple[str, float, int]]):
        # Prefer semantic prefix matches (candidate starts with user query / first token),
        # then year proximity, then score.
        best_pick: tuple[int, int, int, float, str] | None = None  # (starts_with, is_exact, -year_delta, score, model_n)
        for cand_model_n, score, _ in results:
            cand_years = _cand_years(cand_model_n)
            if not cand_years:
                continue

            starts_with = 1 if _starts_with_query(cand_model_n) else 0

            if year in cand_years:
                pick = (starts_with, 1, 0, float(score), cand_model_n)
            else:
                nearby_years = [y for y in cand_years if year - 3 <= y <= year + 3]
                if not nearby_years:
                    continue
                year_delta = min(abs(y - year) for y in nearby_years)
                pick = (starts_with, 0, -year_delta, float(score), cand_model_n)

            if best_pick is None or pick > best_pick:
                best_pick = pick

        if best_pick is None:
            return None
        return best_pick[4], best_pick[3]

    if len(q) >= 4:
        p_results = process.extract(q, model_choices, scorer=fuzz.partial_ratio, limit=60)
        p_results = [r for r in p_results if r[1] >= 80]
        picked = _pick_best(p_results)
        if picked is not None:
            return picked

    t_results = process.extract(q, model_choices, scorer=fuzz.token_set_ratio, limit=80)
    t_results = [r for r in t_results if r[1] >= 72]
    picked = _pick_best(t_results)
    if picked is not None:
        return picked

    w_results = process.extract(q, model_choices, scorer=fuzz.WRatio, limit=60)
    w_results = [r for r in w_results if r[1] >= 60]
    picked = _pick_best(w_results)
    if picked is not None:
        return picked

    # Fall back to score-only selection to preserve legacy behaviour when no
    # candidate exists within the year window.
    return _fuzzy_model_score(q, model_choices)

# ---------------------------------------------------------------------------
# Region / battery-standard detection
# ---------------------------------------------------------------------------

# NS/JIS standard — Japanese, Korean, Chinese makes
_NS_MAKES: frozenset[str] = frozenset({
    "DAIHATSU", "HONDA", "HINO", "ISUZU", "LEXUS",
    "MARUTI SUZUKI", "MAZDA", "MITSUBISHI", "MITSUBISHI FUSO",
    "NISSAN", "NISSAN DIESEL/UD", "SUBARU", "SUZUKI", "TOYOTA",
    # Korean
    "HYUNDAI", "KIA",
    # Chinese
    "CHERY", "DONGFENG", "FAW", "FOTON", "GREAT WALL", "HAVAL", "SAIC MOTORS",
})

# Everything else (European, American, Indian) defaults to DIN
_DIN_MAKES: frozenset[str] = frozenset({
    "AUDI", "BENTLEY", "BMW", "BRABUS", "CADILLAC", "CHEVROLET",
    "CHRYSLER", "CITROEN", "DODGE", "EICHER", "FERRARI", "FIAT",
    "FORD", "JAGUAR", "JEEP", "LANDROVER", "MAN", "MERCEDES",
    "MERCEDES-BENZ", "MINI", "OPEL", "PEUGEOT", "PORSCHE", "RENAULT",
    "ROLLS-ROYCE", "SCANIA", "SKODA", "TATA", "VAUXHALL",
    "VOLKSWAGEN", "VOLVO",
})

# _EU_MAKES, _KOREAN_MAKES and the two _is_*_make() helpers below exist only
# to support _infer_stop_start(), which is currently dead code (see its
# docstring) — none of these four are called from anywhere else. DIN includes
# US/Indian makes, so _EU_MAKES stays conservative to avoid misclassifying
# non-European vehicles if/when _infer_stop_start is wired back in.
_EU_MAKES: frozenset[str] = frozenset({
    "AUDI", "BENTLEY", "BMW", "BRABUS", "CITROEN", "FERRARI", "FIAT",
    "JAGUAR", "LANDROVER", "MERCEDES", "MERCEDES-BENZ", "MINI", "OPEL",
    "PEUGEOT", "PORSCHE", "RENAULT", "ROLLS-ROYCE", "SCANIA", "SKODA",
    "VAUXHALL", "VOLKSWAGEN", "VOLVO",
})

_KOREAN_MAKES: frozenset[str] = frozenset({"HYUNDAI", "KIA"})

# Luxury / premium makes — always receive AGM regardless of year or engine size.
_LUXURY_MAKES: frozenset[str] = frozenset({
    "AUDI", "BENTLEY", "BMW", "CADILLAC", "FERRARI",
    "INFINITI", "JAGUAR", "LANDROVER", "LEXUS", "MASERATI",
    "MERCEDES", "MERCEDES-BENZ", "PORSCHE", "ROLLS-ROYCE", "VOLVO",
})


def _is_european_make(make: str) -> bool:
    """Unused (dead code) — only referenced by the unused _infer_stop_start()."""
    return make.upper().strip() in _EU_MAKES


def _is_korean_make(make: str) -> bool:
    """Unused (dead code) — only referenced by the unused _infer_stop_start()."""
    return make.upper().strip() in _KOREAN_MAKES


def _infer_stop_start(make: str, year: Optional[int], fuel: str) -> bool:
    """
    Infer whether a vehicle is likely stop-start equipped based on make + year.

    Currently unused (dead code): `recommend()` takes `stop_start` as an
    explicit parameter supplied by the caller (the frontend now has its own
    stop-start selector), so this fallback inference never runs. Kept in case
    that explicit input is ever made optional again.
    """
    if fuel == "HYBRID":
        return True  # hybrids always have engine on/off cycling
    if year is None:
        return False

    y = int(year)
    make_u = make.upper().strip()

    if make_u in {"HONDA", "MAZDA"} and y >= 2012:
        return True
    if make_u in {"BMW", "MERCEDES", "MERCEDES-BENZ", "AUDI", "VOLKSWAGEN"} and y >= 2011:
        return True
    if make_u in {"FORD", "PEUGEOT", "RENAULT", "CITROEN"} and y >= 2013:
        return True
    if make_u in {"TOYOTA", "NISSAN"} and fuel == "PETROL" and y >= 2014:
        return True

    return False


def _make_region(make: str) -> str:
    """Return 'NS' or 'DIN' based on the vehicle make."""
    key = make.upper().strip()
    if key in _NS_MAKES:
        return "NS"
    return "DIN"  # default for European / American / unknown makes


def _battery_region(model_key: str) -> str:
    """Return 'DIN' or 'NS' from a battery Model Key string."""
    if not model_key or not isinstance(model_key, str):
        return "NS"
    return "DIN" if model_key.strip().upper().startswith("DIN") else "NS"


# ---------------------------------------------------------------------------
# Fuel-type normalisation
# ---------------------------------------------------------------------------

_FUEL_MAP: dict[str, str] = {
    "GASOLINE":       "PETROL",
    "PETROL":         "PETROL",
    "PETROL/ELECTRIC":"PETROL",
    "DIESEL":         "DIESEL",
    "DEISEL":         "DIESEL",          # typo in source data
    "HYBRID":         "HYBRID",
    "PLUG-IN HYBRID": "HYBRID",
    "PLUG-IN-HYBRID": "HYBRID",
    "EV":             "EV",
    "ELECTRIC(EV)":   "EV",
    "ELECCTRIC":      "EV",              # typo in source data
    "ELECTRIC":       "EV",
}


def _norm_fuel(raw) -> str:
    if not raw or not isinstance(raw, str):
        return "PETROL"
    return _FUEL_MAP.get(raw.strip().upper(), "PETROL")


def _norm_model_key(s: str) -> str:
    """Canonical model name for matching.

    Normalises all common separator/spacing variations so that user inputs
    like "CX5", "CX 5", and "CX-5" resolve to the same key ("CX 5"):
      1. Uppercase + strip
      2. Hyphens → space; collapse repeated spaces
      3. Insert a space at every letter↔digit boundary (CX5 → CX 5)
      4. Final collapse
    """
    s = re.sub(r"[\-]+", " ", s.upper().strip())
    s = re.sub(r"([A-Z])(\d)", r"\1 \2", s)
    s = re.sub(r"(\d)([A-Z])", r"\1 \2", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# Ah bracket rules
# (max_cc_inclusive, petrol_ah, diesel_ah, hybrid_ah)
# ---------------------------------------------------------------------------

_AH_RULES: list[tuple[int, int, int, int]] = [
    (1000,  35,  40,  35),
    (1600,  45,  50,  45),
    (2000,  55,  65,  55),
    (2500,  70,  80,  65),
    (3000,  80,  90,  80),
    (4000,  90, 100,  90),
    (9999, 100, 120, 100),
]

def _year_ah_modifier(year: int) -> int:
    if year >= 2018:
        return 10  # modern electronics era
    if year >= 2012:
        return 5  # early ADAS era
    if year < 2000:
        return -5  # pre-OBD2, minimal load
    return 0


def _target_ah(engine_cc: int, fuel: str, year: Optional[int] = None) -> int:
    if fuel == "EV":
        base = 45  # 12V auxiliary battery sizing is not correlated with traction motor size
    else:
        for max_cc, p_ah, d_ah, h_ah in _AH_RULES:
            if engine_cc <= max_cc:
                if fuel == "DIESEL":
                    base = d_ah
                    break
                if fuel == "HYBRID":
                    base = h_ah
                    break
                base = p_ah
                break
        else:
            base = 100

    if year is not None:
        base += _year_ah_modifier(int(year))
    return base


# ---------------------------------------------------------------------------
# Technology preference per Ah + fuel
# Priority order (highest first): EFB, AGM, MF, SB (Flooded)
# ---------------------------------------------------------------------------

_TECH_PRIORITY = ["EFB", "AGM", "MF", "SB (Flooded)"]


# AGM did not become an OEM fitment on premium cars until stop-start and
# brake-energy regeneration arrived — BMW from roughly 2007, Mercedes 2008.
# Before that even a 7-Series left the factory on a flooded battery, so the
# "premium electronics baseline" reasoning simply does not apply to a 2001
# 320i: it recommends a materially more expensive battery than the car was
# built for, and misstates the fitment in the exported guide. The premium rule
# is therefore gated on the year the technology actually existed; older cars
# fall through to the normal engine/fuel/stop-start logic like any other make.
# Per-make first year AGM became the OEM fitment, anchored on when each brand
# actually shipped stop-start / brake-energy regeneration — the systems AGM was
# introduced to serve. A single industry-wide date is too blunt: BMW was fitting
# AGM in 2007, Maserati not until the Quattroporte VI in 2013, so one cutoff
# either strips AGM from cars that had it or leaves it on cars that never did.
#
# THESE ARE APPROXIMATE BRAND-LEVEL ADOPTION DATES, NOT PER-MODEL FITMENT FACTS.
# Flagship models generally led their brand by a year or two, so a date here may
# be late for a top-of-range car and early for a base one. They are deliberately
# set at the point the technology became normal for the brand rather than at its
# first appearance anywhere in the range, so the rule errs toward the ordinary
# car rather than the halo model. Where Exide's own fitment guide covers a
# vehicle, that data wins over this table — see _fitment_override.
_LUXURY_AGM_FROM: dict[str, int] = {
    "BMW": 2007,            # EfficientDynamics brake-energy regeneration
    "MERCEDES": 2008,       # BlueEFFICIENCY ECO start/stop (W204)
    "MERCEDES-BENZ": 2008,
    "AUDI": 2010,           # start-stop across A4/A5/A6/A8
    "PORSCHE": 2010,        # Panamera, Cayenne 958
    "VOLVO": 2010,          # DRIVe start/stop rollout
    "CADILLAC": 2010,
    "ROLLS-ROYCE": 2010,    # Ghost (BMW N74 platform)
    "FERRARI": 2010,        # HELE start-stop, 458
    "JAGUAR": 2011,         # XF 2.2d start-stop
    "LANDROVER": 2011,      # Evoque; Range Rover/Discovery later still
    "BENTLEY": 2012,        # Continental GT W12
    "LEXUS": 2012,          # late to AGM on non-hybrid models
    "INFINITI": 2013,
    "MASERATI": 2013,       # Quattroporte VI / Ghibli
}
# Fallback for a premium make added to _LUXURY_MAKES without its own date:
# the middle of the industry transition rather than either extreme.
_LUXURY_AGM_FROM_YEAR = 2010


def _luxury_agm(make: str, year: Optional[int]) -> bool:
    """True when a make's premium-AGM baseline applies for that model year."""
    m = make.upper().strip()
    if m not in _LUXURY_MAKES:
        return False
    # Unknown year keeps the previous behaviour: assume the modern fitment
    # rather than downgrade a car we cannot date.
    if year is None:
        return True
    return int(year) >= _LUXURY_AGM_FROM.get(m, _LUXURY_AGM_FROM_YEAR)


def _preferred_tech(
    engine_cc: int,
    fuel: str,
    year: Optional[int],
    make: str,
    stop_start: bool = True,
) -> str:
    """Return the preferred battery technology given engine size and fuel."""
    if fuel == "EV":
        return "MF"
    # Luxury/premium makes need AGM — advanced electronics baseline — but only
    # from the model year AGM was actually fitted. See _luxury_agm.
    if _luxury_agm(make, year):
        return "AGM"
    if fuel == "HYBRID":
        return "EFB"
    if stop_start:
        # i-stop ON: diesel/large engines need AGM; standard engines use EFB.
        if fuel == "DIESEL" or engine_cc >= 2500:
            return "AGM"
        return "EFB"
    # i-stop OFF: standard battery — no stop-start cycling demand.
    return "MF"


# ---------------------------------------------------------------------------
# Data loaders (cached for the lifetime of the process)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _vehicles() -> pd.DataFrame:
    """
    vehicle_years is never written to by the Exide fitment pipeline — its
    coverage additions live in vehicle_years_exide, unioned in here so every
    downstream consumer (get_makes/get_models/get_years, _make_index, and
    Layers 1/2/3's fuzzy matching) sees the combined vehicle universe without
    needing any changes of its own.
    """
    from db import public_engine
    df = pd.read_sql(
        "SELECT make, model, year, engine_capacity, fuel FROM vehicle_years "
        "UNION ALL "
        "SELECT make, model, year, engine_capacity, fuel FROM vehicle_years_exide",
        public_engine,
    )
    df["engine_capacity"] = pd.to_numeric(df["engine_capacity"], errors="coerce")
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    # Normalize keys for robust matching: case-insensitive, trim, and collapse internal whitespace.
    df["make_n"]  = df["make"].astype(str).str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    df["model_n"] = df["model"].astype(str).apply(_norm_model_key)
    df["fuel_n"]  = df["fuel"].apply(_norm_fuel)
    return df


@lru_cache(maxsize=128)
def _make_index(make_n: str) -> tuple[pd.DataFrame, dict[str, tuple[int, ...]]]:
    """
    Precompute, once per make, what `recommend()` and `_fuzzy_model_score_for_year()`
    otherwise re-derive via a fresh pandas scan/filter on every cache-miss call:
    the make-scoped row slice and a `model_n -> sorted years sold` lookup.

    Cleared alongside `_vehicles()` (same trigger — `vehicle_years` changed).
    """
    make_df = _vehicles()[_vehicles()["make_n"] == make_n]
    years_by_model = {
        model_n: tuple(sorted(sub["year"].dropna().unique().astype(int).tolist()))
        for model_n, sub in make_df.groupby("model_n")
    }
    return make_df, years_by_model


@lru_cache(maxsize=1)
def _batteries() -> pd.DataFrame:
    from db import public_engine
    df = pd.read_sql(
        "SELECT battery_code, model_key, ah, cca_en, technology, origin, brand"
        " FROM battery_specs WHERE deleted_at IS NULL",
        public_engine,
    )
    # Rename DB column names back to the Excel names the rest of the code expects.
    df = df.rename(columns={
        "battery_code": "Battery Code",
        "model_key":    "Model Key",
        "ah":           "Ah",
        "cca_en":       "CCA (A EN)",
        "technology":   "Technology",
        "origin":       "Origin",
        "brand":        "Brand",
    })
    df["Ah"] = pd.to_numeric(df["Ah"], errors="coerce")
    df["CCA (A EN)"] = pd.to_numeric(df["CCA (A EN)"], errors="coerce")
    return df


_SPEC_TOLERANCE = 0.15  # ±15% window for AH/CCA spec search


def search_by_specs(ah: float | None = None, cca: float | None = None) -> list[dict]:
    """Return all active batteries within ±15% of the given AH and/or CCA, sorted by closeness."""
    df = _batteries().copy()

    mask = pd.Series([True] * len(df), index=df.index)
    if ah is not None:
        lo, hi = ah * (1 - _SPEC_TOLERANCE), ah * (1 + _SPEC_TOLERANCE)
        mask &= df["Ah"].between(lo, hi)
    if cca is not None:
        lo, hi = cca * (1 - _SPEC_TOLERANCE), cca * (1 + _SPEC_TOLERANCE)
        mask &= df["CCA (A EN)"].between(lo, hi)

    hits = df[mask].copy()
    if hits.empty:
        return []

    hits["_ah_dev"]  = ((hits["Ah"]         - ah)  / ah).abs()  if ah  is not None else 0.0
    hits["_cca_dev"] = ((hits["CCA (A EN)"] - cca) / cca).abs() if cca is not None else 0.0
    hits["_score"]   = hits["_ah_dev"] + hits["_cca_dev"]
    hits = hits.sort_values("_score")

    results = []
    for _, r in hits.iterrows():
        results.append({
            "battery_code": r["Battery Code"],
            "model_key":    r["Model Key"],
            "ah":           None if pd.isna(r["Ah"])          else float(r["Ah"]),
            "cca":          None if pd.isna(r["CCA (A EN)"])  else float(r["CCA (A EN)"]),
            "technology":   r["Technology"] if pd.notna(r["Technology"]) else None,
            "brand":        r["Brand"]      if pd.notna(r["Brand"])      else None,
            "origin":       r["Origin"]     if pd.notna(r["Origin"])     else None,
            "match_type":   "direct" if r["_score"] < 0.05 else "close",
        })
    return results


@lru_cache(maxsize=1)
def _inference() -> pd.DataFrame:
    """
    Load dial_battery_inference (real-world order data) into memory.
    Returns an empty DataFrame if the table is missing or empty.
    """
    from db import public_engine
    try:
        df = pd.read_sql(
            "SELECT vehicle_type, vehicle_model, battery_code, frequency, last_sale_date"
            " FROM dial_battery_inference",
            public_engine,
        )
    except Exception:
        return pd.DataFrame(
            columns=["vehicle_type", "vehicle_model", "battery_code", "frequency",
                     "last_sale_date", "vtype_n", "vmodel_n", "bcode_n"]
        )
    if df.empty:
        return df
    df["last_sale_date"] = pd.to_datetime(df["last_sale_date"], errors="coerce", utc=True)
    df["vtype_n"]  = df["vehicle_type"].astype(str).str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    df["vmodel_n"] = df["vehicle_model"].astype(str).apply(_norm_model_key)
    df["bcode_n"]  = df["battery_code"].astype(str).str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    return df


_TRAILING_CHASSIS_CODE_RE = re.compile(r"\s*\([^)]*\)?\s*$")


def _strip_trailing_chassis_code(model: str) -> str:
    """
    Strip a trailing '(...)' chassis-code block, e.g. '124 Spider 1.4( 348)'
    -> '124 Spider 1.4'. Mirrors pipelines/exide_fitment_clean.py's
    _strip_chassis_code_suffix() — kept as a separate small copy here rather
    than importing the pipeline script into the runtime module. Applied when
    building oem_fitment's model_n so it matches vehicle_years_exide's
    already-stripped display model (which is what a matched vehicle's model
    actually looks like by the time _fitment_override() is called) — without
    this, a vehicle exploded from a given oem_fitment row could fail to
    fuzzy-match back to that same row's fitment spec.
    """
    stripped = _TRAILING_CHASSIS_CODE_RE.sub("", model).strip()
    return stripped if stripped else model


@lru_cache(maxsize=1)
def _fitment() -> pd.DataFrame:
    """
    Load oem_fitment (Exide's official global fitment guide) into memory.
    Returns an empty DataFrame if the table is missing or empty.
    """
    from db import public_engine
    try:
        df = pd.read_sql(
            "SELECT make, model, year_from, year_to, ah, technology FROM oem_fitment",
            public_engine,
        )
    except Exception:
        return pd.DataFrame(
            columns=["make", "model", "year_from", "year_to", "ah", "technology", "make_n", "model_n"]
        )
    if df.empty:
        return df
    df["make_n"]    = df["make"].astype(str).str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    df["model_n"]   = df["model"].astype(str).apply(_strip_trailing_chassis_code).apply(_norm_model_key)
    df["year_from"] = pd.to_numeric(df["year_from"], errors="coerce").astype("Int64")
    df["year_to"]   = pd.to_numeric(df["year_to"], errors="coerce").astype("Int64")  # NaN = open-ended
    df["ah"]        = pd.to_numeric(df["ah"], errors="coerce")
    return df


@lru_cache(maxsize=1)
def _web_validation() -> pd.DataFrame:
    """
    Load web_battery_validation (internet-sourced fitment data) into memory.
    Returns an empty DataFrame if the table is missing or empty.
    """
    from db import public_engine
    try:
        df = pd.read_sql(
            "SELECT make_n, model_n, year, battery_code, ah, technology"
            " FROM web_battery_validation",
            public_engine,
        )
    except Exception:
        return pd.DataFrame(
            columns=["make_n", "model_n", "year", "battery_code", "ah", "technology"]
        )
    if df.empty:
        return df
    df["make_n"]  = df["make_n"].astype(str).str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    df["model_n"] = df["model_n"].astype(str).apply(_norm_model_key)
    df["year"]    = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    return df


@lru_cache(maxsize=1)
def _model_aliases() -> pd.DataFrame:
    """
    Alias table mapping international model names to JDM model names
    stored in vehicle_years.

    Loaded once from the model_aliases table in PostgreSQL.
    Returns an empty DataFrame (with the expected columns) if the table is
    empty or cannot be queried.
    """
    from db import public_engine
    try:
        df = pd.read_sql(
            "SELECT make, international_model, jdm_model, priority FROM model_aliases",
            public_engine,
        )
    except Exception:
        return pd.DataFrame(columns=["make_n", "intl_model_n", "jdm_model_n", "priority"])

    if df.empty:
        return pd.DataFrame(columns=["make_n", "intl_model_n", "jdm_model_n", "priority"])

    out = pd.DataFrame()
    out["make_n"]       = df["make"].astype(str).str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    out["intl_model_n"] = df["international_model"].astype(str).str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    out["jdm_model_n"]  = df["jdm_model"].astype(str).str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    out["priority"]     = pd.to_numeric(df["priority"], errors="coerce").fillna(999).astype(int)
    out = out[(out["make_n"] != "") & (out["intl_model_n"] != "") & (out["jdm_model_n"] != "")]
    return out.drop_duplicates()


# ---------------------------------------------------------------------------
# Inference helpers (Layer 0)
# ---------------------------------------------------------------------------

def _inference_lookup(
    make_n: str,
    model_n: str,
) -> tuple[str, str, int] | None:
    """
    Return (battery_code, matched_model_n, confidence) from the inference table,
    or None if no reliable match exists.

    Exact model match → confidence 95.
    Fuzzy model match (token_set_ratio ≥ 85) → confidence 80.
    """
    inf = _inference()
    if inf.empty:
        return None

    make_rows = inf[inf["vtype_n"] == make_n]
    if make_rows.empty:
        return None

    model_choices = make_rows["vmodel_n"].unique().tolist()

    if model_n in model_choices:
        matched_model_n = model_n
        confidence = 95
    else:
        result = process.extractOne(model_n, model_choices, scorer=fuzz.token_set_ratio)
        if not result or result[1] < 85:
            return None
        matched_model_n = result[0]
        confidence = 80

    # Pick the best battery for this (make, model) pair.
    # Primary sort: highest frequency. Tiebreaker: most recent sale date.
    matched_rows = make_rows[make_rows["vmodel_n"] == matched_model_n].copy()
    matched_rows["_sort_date"] = matched_rows["last_sale_date"].fillna(
        pd.Timestamp.min.tz_localize("UTC")
    )
    best = matched_rows.sort_values(
        ["frequency", "_sort_date"], ascending=[False, False]
    ).iloc[0]
    return str(best["bcode_n"]), matched_model_n, confidence


def _web_validation_lookup(
    make_n: str,
    model_n: str,
    year: int,
) -> tuple[str, str, int] | None:
    """
    Return (battery_code, matched_model_n, confidence) from web_battery_validation,
    or None if no entry exists.

    Exact year + exact model  → confidence 90
    Exact year + fuzzy model (token_set_ratio ≥ 85) → confidence 75
    """
    wv = _web_validation()
    if wv.empty:
        return None

    make_rows = wv[wv["make_n"] == make_n]
    if make_rows.empty:
        return None

    year_rows = make_rows[make_rows["year"] == year]
    if year_rows.empty:
        return None

    model_choices = year_rows["model_n"].unique().tolist()

    if model_n in model_choices:
        row = year_rows[year_rows["model_n"] == model_n].iloc[0]
        return str(row["battery_code"]), model_n, 90

    result = process.extractOne(model_n, model_choices, scorer=fuzz.token_set_ratio)
    if not result or result[1] < 85:
        return None
    row = year_rows[year_rows["model_n"] == result[0]].iloc[0]
    return str(row["battery_code"]), result[0], 75


def _fitment_override(make_n: str, model_n: str, year: int, preferred_tech: str | None = None) -> tuple[float, str | None] | None:
    """
    Return (ah, technology) from oem_fitment for this vehicle, or None if no
    row covers it. Not a vehicle-match layer — this is only ever consulted
    for a (make, model, year) some other layer already resolved, and when it
    hits, its Ah REPLACES that layer's own value (see module docstring). No
    confidence value: this doesn't affect how sure we are about the vehicle
    match, only the precision of the Ah used.

    The technology in the returned tuple is informational only — callers
    apply the Ah but deliberately do NOT apply this technology to
    preferred_tech (see module docstring: luxury-make/stop-start rules take
    precedence over Exide's per-vehicle tech value).

    Exact model match within [year_from, year_to] (open-ended if year_to is
    null) → used directly. Otherwise fuzzy model match (token_set_ratio ≥ 85)
    within the same year range — pooling every model tied at the best score,
    not just extractOne's arbitrary pick among ties. A bare query like
    "OUTLANDER" is a subset-match (score 100) against many different Exide
    trims at once ("OUTLANDER III 2.0 4WD", "OUTLANDER III 2.2 DI-D", the
    hybrid variant, ...); committing to whichever one extractOne happens to
    return first could land on an unrepresentative trim (e.g. the hybrid's
    45Ah) instead of a sensible one. Rows with a null Ah are skipped — a
    technology-only hint isn't enough to drive battery selection.

    A single model/year-range legitimately has multiple oem_fitment rows —
    Exide lists several battery tiers for the same trim (e.g. a base 50Ah/MF
    option alongside 55Ah/EFB and 60Ah/EFB upgrades). Among tied model
    candidates, prefer whichever tier's technology matches the caller's
    already-decided preferred_tech (from luxury-make/stop-start rules, see
    module docstring) before falling back to highest Ah — this keeps the Ah
    figure paired with a technology Exide actually offered it at, instead of
    borrowing an Ah number from a tier tagged with a different chemistry
    than the one we're about to sell.
    """
    fit = _fitment()
    if fit.empty:
        return None

    make_rows = fit[fit["make_n"] == make_n]
    if make_rows.empty:
        return None

    year_mask = (make_rows["year_from"] <= year) & (
        make_rows["year_to"].isna() | (make_rows["year_to"] >= year)
    )
    year_rows = make_rows[year_mask]
    if year_rows.empty:
        return None

    model_choices = year_rows["model_n"].unique().tolist()

    if model_n in model_choices:
        matched_model_ns = [model_n]
    else:
        scored = process.extract(model_n, model_choices, scorer=fuzz.token_set_ratio, limit=None)
        if not scored:
            return None
        best_score = scored[0][1]
        if best_score < 85:
            return None
        matched_model_ns = [m for m, score, _ in scored if score == best_score]

    candidates = year_rows[year_rows["model_n"].isin(matched_model_ns) & year_rows["ah"].notna()]
    if candidates.empty:
        return None

    # Prefer the tier whose technology matches what the caller already
    # decided preferred_tech should be — only fall back to "highest Ah
    # overall" when none of the tiers match (or the caller didn't have a
    # preference to match against).
    tech_matched = candidates
    if preferred_tech:
        tech_matched = candidates[candidates["technology"] == preferred_tech]
        if tech_matched.empty:
            tech_matched = candidates

    best = tech_matched.sort_values("ah", ascending=False).iloc[0]
    tech = str(best["technology"]) if pd.notna(best["technology"]) else None
    return float(best["ah"]), tech


def _parse_inference_code(code: str) -> tuple[int, str] | None:
    """
    Parse a call-centre battery code to extract (target_ah, technology).
    Returns None if the format is not recognised.

    Handles:
      DIN {ah}[MF|AGM|EFB] ... → e.g. "DIN 043 EXIDE MF", "DIN 060MF L EXIDE AGM"
      NS{ah}[...]              → e.g. "NS60", "NS70 ATLAS"
    """
    if not code or not isinstance(code, str):
        return None
    c = code.strip().upper()

    if "AGM" in c:
        tech = "AGM"
    elif "EFB" in c:
        tech = "EFB"
    else:
        tech = "MF"

    din_match = re.match(r"DIN\s+0*(\d+)", c)
    if din_match:
        return int(din_match.group(1)), tech

    ns_match = re.match(r"NS\s*0*(\d+)", c)
    if ns_match:
        return int(ns_match.group(1)), tech

    return None


def _lookup_battery_by_code(code: str) -> tuple[int, str] | None:
    """
    Resolve a call-centre battery code to (target_ah, technology) by matching
    directly against battery_specs — no format parsing required.

    Priority:
      1. Exact code match in battery_specs
      2. Fuzzy match (token_set_ratio ≥ 85) in battery_specs
      3. Legacy format parser (_parse_inference_code) as last resort
    Returns None only when all three fail.
    """
    if not code or not isinstance(code, str):
        return None

    batt = _batteries()
    code_n = code.strip().upper()
    batt_codes = batt["Battery Code"].str.upper().str.strip()

    exact = batt[batt_codes == code_n]
    if not exact.empty:
        row = exact.iloc[0]
        return int(row["Ah"]), str(row["Technology"])

    batt_codes_list = batt_codes.tolist()
    hit = process.extractOne(code_n, batt_codes_list, scorer=fuzz.token_set_ratio)
    if hit and hit[1] >= 85:
        row = batt.iloc[batt_codes_list.index(hit[0])]
        return int(row["Ah"]), str(row["Technology"])

    return _parse_inference_code(code)


# ---------------------------------------------------------------------------
# Battery selector
# ---------------------------------------------------------------------------

def _select_batteries(
    target_ah: int,
    preferred_tech: str,
    region: str = "NS",
) -> tuple[dict, list[dict]]:
    """
    Return (primary, alternatives) from battery_specs.

    Primary      — best technology match at target_ah within the given region.
    Alternatives — same Ah, same CCA, same technology as primary; only the
                   battery code (brand/variant) may differ. Capped at 6.
    Region       — 'NS' (Japanese/Korean/Chinese) or 'DIN' (European/American).
    """
    batt = _batteries()

    batt = batt[batt["Model Key"].apply(lambda k: _battery_region(str(k)) == region)]

    def _row_to_dict(row: pd.Series) -> dict:
        return {
            "battery_code": row["Battery Code"],
            "model_key":    row["Model Key"],
            "ah":           int(row["Ah"]),
            "cca_en":       int(row["CCA (A EN)"]) if pd.notna(row["CCA (A EN)"]) else None,
            "technology":   row["Technology"],
            "origin":       row["Origin"] if pd.notna(row.get("Origin")) else None,
        }

    def _origin_pref(val) -> int:
        """0 = imported (first), 1 = everything else."""
        return 0 if str(val).lower() == "imported" else 1

    exact_ah = batt[batt["Ah"] == target_ah]

    tech_order = {t: i for i, t in enumerate(_TECH_PRIORITY)}
    exact_sorted = exact_ah.copy()
    exact_sorted["_pref"] = exact_sorted["Technology"].map(
        lambda t: tech_order.get(t, 99)
    )
    # Within the same technology, imported batteries precede local ones.
    exact_sorted["_origin_pref"] = exact_sorted["Origin"].map(_origin_pref)
    exact_sorted = exact_sorted.sort_values(["_pref", "_origin_pref"])

    preferred = exact_sorted[exact_sorted["Technology"] == preferred_tech]
    if not preferred.empty:
        primary_row = preferred.iloc[0]
    elif not exact_sorted.empty:
        # Preferred tech not available at target Ah → use best available tech at same Ah.
        primary_row = exact_sorted.iloc[0]
    else:
        # Nothing stocked at target Ah → nearest Ah in any tech.
        nearest_idx = (batt["Ah"] - target_ah).abs().idxmin()
        primary_row = cast(pd.Series, batt.loc[[nearest_idx]].iloc[0])

    primary = _row_to_dict(primary_row)
    primary_tech = primary_row["Technology"]
    primary_cca  = int(primary_row["CCA (A EN)"]) if pd.notna(primary_row["CCA (A EN)"]) else None
    primary_ah_val = int(primary_row["Ah"]) if pd.notna(primary_row["Ah"]) else target_ah

    # Alternatives: same Ah + same CCA + same technology as actual primary.
    # Use primary_ah_val (not target_ah) because the primary may have stepped
    # to a different Ah when the preferred tech was unavailable at target_ah.
    same_ah_pool = batt[batt["Ah"] == primary_ah_val]
    alt_mask = (
        (same_ah_pool["Battery Code"] != primary_row["Battery Code"]) &
        (same_ah_pool["Technology"] == primary_tech)
    )
    if primary_cca is not None:
        alt_mask = alt_mask & same_ah_pool["CCA (A EN)"].apply(
            lambda c: pd.notna(c) and int(c) == primary_cca
        )
    alt_rows = same_ah_pool[alt_mask].copy()
    # Imported alternatives precede local ones.
    alt_rows["_origin_pref"] = alt_rows["Origin"].map(_origin_pref)
    alt_rows = alt_rows.sort_values("_origin_pref")
    alternatives = [_row_to_dict(r) for _, r in alt_rows.iterrows()]

    return primary, alternatives[:6]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_makes() -> list[str]:
    return sorted(_vehicles()["make"].dropna().unique().tolist())


def get_models(make: str) -> list[str]:
    df = _vehicles()
    subset = df[df["make_n"] == make.upper().strip()]
    return sorted(subset["model"].dropna().unique().tolist())


def get_years(make: str, model: str) -> list[int]:
    df = _vehicles()
    make_n  = make.upper().strip()
    model_n = _norm_model_key(model)
    subset = df[(df["make_n"] == make_n) & (df["model_n"] == model_n)]
    return sorted(subset["year"].dropna().unique().astype(int).tolist(), reverse=True)


@lru_cache(maxsize=512)
def recommend(
    make: str,
    model: str,
    year: int,
    engine_cc: Optional[int] = None,
    fuel_type: Optional[str] = None,
    enable_aliases: bool = True,
    stop_start: bool = True,
) -> dict:
    df = _vehicles()
    make_n  = make.upper().strip()
    model_n = _norm_model_key(model)

    resolved_cc:   int  = engine_cc or 1500
    resolved_fuel: str  = _norm_fuel(fuel_type)
    matched_make:  str | None  = None
    matched_model: str | None  = None
    matched_year:  int | None  = None
    confidence:    int  = 40
    match_type:    str  = "Estimated (Rule-Based)"

    # ── Layer 0a: Web validation — internet-accepted battery ──────────────
    # Year-specific lookup against web_battery_validation, populated offline
    # by pipelines/web_battery_validate.py. Wins over inference because it
    # reflects current fitment standards rather than historical sales.
    web_hit = _web_validation_lookup(make_n, model_n, int(year))
    if web_hit is not None:
        web_code, web_matched_model_n, web_confidence = web_hit
        region = _make_region(make_n)

        # Resolve engine specs from vehicle_years for response reporting.
        web_make_df, web_years_by_model = _make_index(make_n)
        web_matched_year: int | None = None
        web_veh_model_n: str | None = None

        if not web_make_df.empty:
            if model_n in web_years_by_model:
                web_veh_model_n: str | None = model_n
            else:
                web_veh_best = _fuzzy_model_score_for_year(model_n, web_make_df, int(year), web_years_by_model)
                web_veh_model_n = web_veh_best[0] if web_veh_best else None

            if web_veh_model_n is not None:
                web_model_df = web_make_df[web_make_df["model_n"] == web_veh_model_n]
                exact_yr = web_model_df[web_model_df["year"] == year]
                if not exact_yr.empty:
                    vrow = exact_yr.iloc[0]
                    web_matched_year = int(vrow["year"])
                    if pd.notna(vrow.get("engine_capacity")):
                        resolved_cc = int(vrow["engine_capacity"])
                    if pd.notna(vrow.get("fuel")):
                        resolved_fuel = _norm_fuel(str(vrow["fuel"]))
                else:
                    nearby = web_model_df[
                        (web_model_df["year"] >= year - 3) &
                        (web_model_df["year"] <= year + 3)
                    ]
                    if not nearby.empty:
                        vrow = nearby.iloc[(nearby["year"] - year).abs().argsort().iloc[0]]
                        web_matched_year = int(vrow["year"])
                        if pd.notna(vrow.get("engine_capacity")):
                            resolved_cc = int(vrow["engine_capacity"])
                        if pd.notna(vrow.get("fuel")):
                            resolved_fuel = _norm_fuel(str(vrow["fuel"]))

        effective_web_year = web_matched_year if web_matched_year is not None else int(year)

        parsed = _lookup_battery_by_code(web_code)
        if parsed is not None:
            target_ah, parsed_tech = parsed
            if _luxury_agm(make_n, effective_web_year):
                pref_tech = "AGM"
            elif not stop_start:
                pref_tech = _preferred_tech(resolved_cc, resolved_fuel, effective_web_year, make_n, False)
            elif parsed_tech in ("AGM", "EFB"):
                pref_tech = parsed_tech
            else:
                pref_tech = _preferred_tech(resolved_cc, resolved_fuel, effective_web_year, make_n, True)
        else:
            target_ah = _target_ah(resolved_cc, resolved_fuel, effective_web_year)
            pref_tech = _preferred_tech(resolved_cc, resolved_fuel, effective_web_year, make_n, stop_start)

        ah_source = "battery_code"
        fit = _fitment_override(make_n, web_veh_model_n or model_n, effective_web_year, pref_tech)
        if fit is not None:
            fit_ah, _fit_tech = fit
            target_ah = int(round(fit_ah))
            ah_source = "oem_fitment"

        primary, alternatives = _select_batteries(target_ah, pref_tech, region)

        return {
            "make":           make_n,
            "model":          model_n,
            "year":           year,
            "engine_cc":      resolved_cc,
            "fuel_type":      resolved_fuel,
            "battery_region": region,
            "recommended_ah": target_ah,
            "preferred_tech": pref_tech,
            "confidence":     web_confidence,
            "match_type":     "Web-Validated Match",
            "matched_make":   make_n,
            "matched_model":  web_matched_model_n,
            "matched_year":   web_matched_year,
            "ah_source":      ah_source,
            "primary":        primary,
            "alternatives":   alternatives,
        }

    # ── Layer 0b: Inference — real-world order data ────────────────────
    # The highest-frequency call-centre battery code for this make/model
    # is the authoritative source for Ah and technology — it records what
    # real customers were actually sold. Vehicle_years is still consulted
    # for engine specs to populate the response. Rules are the fallback only
    # when the battery code cannot be parsed.
    inf_hit = _inference_lookup(make_n, model_n)
    if inf_hit is not None:
        inf_code, inf_matched_model_n, inf_confidence = inf_hit
        region = _make_region(make_n)

        # Resolve engine specs from vehicle_years for response reporting.
        inf_make_df, inf_years_by_model = _make_index(make_n)
        inf_matched_year: int | None = None
        veh_model_n: str | None = None

        if not inf_make_df.empty:
            if model_n in inf_years_by_model:
                veh_model_n: str | None = model_n
            else:
                veh_best = _fuzzy_model_score_for_year(model_n, inf_make_df, int(year), inf_years_by_model)
                veh_model_n = veh_best[0] if veh_best else None

            if veh_model_n is not None:
                veh_model_df = inf_make_df[inf_make_df["model_n"] == veh_model_n]
                exact_yr = veh_model_df[veh_model_df["year"] == year]
                if not exact_yr.empty:
                    vrow = exact_yr.iloc[0]
                    inf_matched_year = int(vrow["year"])
                    if pd.notna(vrow.get("engine_capacity")):
                        resolved_cc = int(vrow["engine_capacity"])
                    if pd.notna(vrow.get("fuel")):
                        resolved_fuel = _norm_fuel(str(vrow["fuel"]))
                else:
                    nearby = veh_model_df[
                        (veh_model_df["year"] >= year - 3) &
                        (veh_model_df["year"] <= year + 3)
                    ]
                    if not nearby.empty:
                        vrow = nearby.iloc[(nearby["year"] - year).abs().argsort().iloc[0]]
                        inf_matched_year = int(vrow["year"])
                        if pd.notna(vrow.get("engine_capacity")):
                            resolved_cc = int(vrow["engine_capacity"])
                        if pd.notna(vrow.get("fuel")):
                            resolved_fuel = _norm_fuel(str(vrow["fuel"]))

        effective_inf_year = inf_matched_year if inf_matched_year is not None else int(year)

        # Resolve Ah + technology from the inference battery code by matching
        # directly against battery_specs (exact → fuzzy → legacy parser).
        # Ah always comes from the real-world inference data.
        # Technology: honour AGM/EFB from inference (deliberate upgrade by call centre);
        # but when inference says MF, let stop_start determine the correct tech —
        # MF codes in the inference table often reflect non-i-stop sales or wrong
        # recommendations, so we should not blindly copy them for i-stop vehicles.
        parsed = _lookup_battery_by_code(inf_code)
        if parsed is not None:
            target_ah, parsed_tech = parsed
            if _luxury_agm(make_n, effective_inf_year):
                pref_tech = "AGM"
            elif not stop_start:
                pref_tech = _preferred_tech(resolved_cc, resolved_fuel, effective_inf_year, make_n, False)
            elif parsed_tech in ("AGM", "EFB"):
                pref_tech = parsed_tech
            else:
                pref_tech = _preferred_tech(resolved_cc, resolved_fuel, effective_inf_year, make_n, True)
        else:
            target_ah = _target_ah(resolved_cc, resolved_fuel, effective_inf_year)
            pref_tech = _preferred_tech(resolved_cc, resolved_fuel, effective_inf_year, make_n, stop_start)

        ah_source = "battery_code"
        fit = _fitment_override(make_n, veh_model_n or model_n, effective_inf_year, pref_tech)
        if fit is not None:
            fit_ah, _fit_tech = fit
            target_ah = int(round(fit_ah))
            ah_source = "oem_fitment"

        primary, alternatives = _select_batteries(target_ah, pref_tech, region)

        return {
            "make":           make_n,
            "model":          model_n,
            "year":           year,
            "engine_cc":      resolved_cc,
            "fuel_type":      resolved_fuel,
            "battery_region": region,
            "recommended_ah": target_ah,
            "preferred_tech": pref_tech,
            "confidence":     inf_confidence,
            "match_type":     "Real-World Data Match",
            "matched_make":   make_n,
            "matched_model":  inf_matched_model_n,
            "matched_year":   inf_matched_year,
            "ah_source":      ah_source,
            "primary":        primary,
            "alternatives":   alternatives,
        }

    # ── Step 1: filter to the requested make ───────────────────────────
    make_df, years_by_model = _make_index(make_n)

    if make_df.empty:
        # Fuzzy fallback for make
        all_makes = df["make_n"].unique().tolist()
        best_make_match = process.extractOne(make_n, all_makes, scorer=fuzz.WRatio)
        if best_make_match and best_make_match[1] >= 75:
            make_n  = best_make_match[0]
            make_df, years_by_model = _make_index(make_n)

    # ── Step 2: fuzzy-match the model ──────────────────────────────────
    if not make_df.empty:
        model_choices = list(years_by_model.keys())

        # Prefer exact model-key hits over fuzzy selection. This prevents
        # trim-variant drift where a longer candidate can tie at score=100.
        if model_n in model_choices:
            best_model = (model_n, 100.0)
        else:
            best_model = _fuzzy_model_score_for_year(model_n, make_df, int(year), years_by_model)

        if best_model is not None:
            matched_model_n, model_score = best_model
            model_df = make_df[make_df["model_n"] == matched_model_n]

            # ── Step 3a: exact year within matched model ────────────────
            exact_year_df = model_df[model_df["year"] == year]
            if not exact_year_df.empty:
                row = exact_year_df.iloc[0]
                confidence  = 100 if model_score >= 90 else int(model_score)
                match_type  = "Exact Match" if model_score >= 90 else "Close Match"
                matched_make  = str(row["make"])
                matched_model = str(row["model"])
                matched_year  = int(row["year"])
                # On dataset matches, the dataset is authoritative for cc/fuel when present.
                if pd.notna(row.get("engine_capacity")):
                    resolved_cc = int(row["engine_capacity"])
                if pd.notna(row.get("fuel")):
                    resolved_fuel = _norm_fuel(str(row["fuel"]))

            # ── Step 3b: soft year match (±3) ──────────────────────────
            else:
                nearby_df = model_df[
                    (model_df["year"] >= year - 3) &
                    (model_df["year"] <= year + 3)
                ]
                if not nearby_df.empty:
                    # Pick the row with the closest year
                    nearest = nearby_df.iloc[
                        (nearby_df["year"] - year).abs().argsort().iloc[0]
                    ]
                    year_delta  = abs(int(nearest["year"]) - year)
                    confidence  = max(60, int(model_score) - year_delta * 3)
                    match_type  = "Close Match"
                    matched_make  = str(nearest["make"])
                    matched_model = str(nearest["model"])
                    matched_year  = int(nearest["year"])
                    if pd.notna(nearest.get("engine_capacity")):
                        resolved_cc = int(nearest["engine_capacity"])
                    if pd.notna(nearest.get("fuel")):
                        resolved_fuel = _norm_fuel(str(nearest["fuel"]))

        if enable_aliases and matched_year is None:
            # International model aliases -> JDM model names in the dataset.
            alias_df = _model_aliases()
            make_aliases = alias_df[alias_df["make_n"] == make_n]
            intl_choices = make_aliases["intl_model_n"].dropna().unique().tolist()
            best_alias = process.extractOne(model_n, intl_choices, scorer=fuzz.WRatio) if intl_choices else None

            if best_alias and best_alias[1] >= 75:
                alias_key = best_alias[0]
                alias_score = int(best_alias[1])
                jdm_aliases = (
                    make_aliases[make_aliases["intl_model_n"] == alias_key][["jdm_model_n", "priority"]]
                    .dropna(subset=["jdm_model_n"])
                    .drop_duplicates()
                    .sort_values(["priority", "jdm_model_n"], ascending=[True, True])
                )

                # Resolve each JDM alias to a real dataset model via fuzzy match.
                resolved_candidates: list[tuple[str, int, int]] = []  # (model_n, jdm_score, alias_priority)
                for _, alias_row in jdm_aliases.iterrows():
                    jdm = str(alias_row["jdm_model_n"])
                    alias_priority = int(alias_row.get("priority", 999))
                    best_jdm = process.extractOne(jdm, model_choices, scorer=fuzz.WRatio)
                    if best_jdm and best_jdm[1] >= 75:
                        resolved_candidates.append((best_jdm[0], int(best_jdm[1]), alias_priority))

                # Pick the best candidate by year proximity (exact year first),
                # then smallest delta, then highest JDM-model similarity.
                best_pick: tuple[int, int, int, int, str] | None = None  # (is_exact, -year_delta, -alias_priority, jdm_score, model_n)
                for cand_model_n, jdm_score, alias_priority in sorted(set(resolved_candidates)):
                    cand_years = years_by_model.get(cand_model_n, ())
                    if year in cand_years:
                        pick = (1, 0, -int(alias_priority), jdm_score, cand_model_n)
                        if best_pick is None or pick > best_pick:
                            best_pick = pick
                        continue

                    nearby_years = [y for y in cand_years if year - 3 <= y <= year + 3]
                    if not nearby_years:
                        continue
                    year_delta = min(abs(y - year) for y in nearby_years)
                    pick = (0, -year_delta, -int(alias_priority), jdm_score, cand_model_n)
                    if best_pick is None or pick > best_pick:
                        best_pick = pick

                if best_pick is not None:
                    matched_model_n = best_pick[4]
                    model_score = alias_score
                    model_df = make_df[make_df["model_n"] == matched_model_n]

                    exact_year_df = model_df[model_df["year"] == year]
                    if not exact_year_df.empty:
                        row = exact_year_df.iloc[0]
                        confidence = 100 if model_score >= 90 else int(model_score)
                        match_type = "Exact Match" if model_score >= 90 else "Close Match"
                        matched_make = str(row["make"])
                        matched_model = str(row["model"])
                        matched_year = int(row["year"])
                        if pd.notna(row.get("engine_capacity")):
                            resolved_cc = int(row["engine_capacity"])
                        if pd.notna(row.get("fuel")):
                            resolved_fuel = _norm_fuel(str(row["fuel"]))
                    else:
                        nearby_df = model_df[
                            (model_df["year"] >= year - 3) &
                            (model_df["year"] <= year + 3)
                        ]
                        if not nearby_df.empty:
                            nearest = nearby_df.iloc[
                                (nearby_df["year"] - year).abs().argsort().iloc[0]
                            ]
                            year_delta = abs(int(nearest["year"]) - year)
                            confidence = max(60, int(model_score) - year_delta * 3)
                            match_type = "Close Match"
                            matched_make = str(nearest["make"])
                            matched_model = str(nearest["model"])
                            matched_year = int(nearest["year"])
                            if pd.notna(nearest.get("engine_capacity")):
                                resolved_cc = int(nearest["engine_capacity"])
                            if pd.notna(nearest.get("fuel")):
                                resolved_fuel = _norm_fuel(str(nearest["fuel"]))

    # ── Step 4: compute target Ah + technology preference ──────────────
    effective_year = int(matched_year) if matched_year is not None else int(year)

    # Guard against erroneous pre-2000 HYBRID labels in the dataset.
    if resolved_fuel == "HYBRID" and effective_year < 2000:
        resolved_fuel = "PETROL"

    rule_based = confidence == 40
    region = _make_region(make_n)
    target_ah = _target_ah(resolved_cc, resolved_fuel, effective_year if rule_based else None)
    pref_tech = _preferred_tech(resolved_cc, resolved_fuel, effective_year, make_n, stop_start)

    ah_source = "cc_bracket_estimate"
    fit_model_n = _norm_model_key(matched_model) if matched_model else model_n
    fit = _fitment_override(make_n, fit_model_n, effective_year, pref_tech)
    if fit is not None:
        fit_ah, _fit_tech = fit
        target_ah = int(round(fit_ah))
        ah_source = "oem_fitment"

    primary, alternatives = _select_batteries(target_ah, pref_tech, region)

    return {
        "make":           make_n,
        "model":          model_n,
        "year":           year,
        "engine_cc":      resolved_cc,
        "fuel_type":      resolved_fuel,
        "battery_region": region,
        "recommended_ah": target_ah,
        "preferred_tech": pref_tech,
        "confidence":     confidence,
        "match_type":     match_type,
        "matched_make":   matched_make,
        "matched_model":  matched_model,
        "matched_year":   matched_year,
        "ah_source":      ah_source,
        "primary":        primary,
        "alternatives":   alternatives,
    }
