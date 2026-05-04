"""
Battery recommendation rule engine.

Data sources
------------
vehicle_years.csv        : make, model, year, engine_capacity, fuel
battery_specs_output.xlsx: Battery Code, Model Key, Ah, CCA (A EN), Technology

Matching layers
---------------
1. Exact   — make + fuzzy model (≥90) + exact year          → confidence 100
2. Soft    — make + fuzzy model (≥60) + year within ±3      → confidence 60–89
3. Rule    — engine_cc + normalised fuel_type → Ah bracket  → confidence 40
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Optional, cast

import pandas as pd
from rapidfuzz import process, fuzz

_BASE = os.path.dirname(os.path.abspath(__file__))


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
) -> tuple[str, float] | None:
    """Like `_fuzzy_model_score`, but prefers candidates that exist near `year`.

    This avoids token-set tie pitfalls where many trims score 100 against a short
    base model name (e.g. "FIT" matches many "FIT ..." trims), by selecting a
    candidate model that has an exact (or ±3-year) row in `vehicle_years.csv`.
    """
    if make_df is None or make_df.empty:
        return None

    model_choices = make_df["model_n"].dropna().unique().tolist()
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

    def _pick_best(results: list[tuple[str, float, int]]):
        # Prefer semantic prefix matches (candidate starts with user query / first token),
        # then year proximity, then score.
        best_pick: tuple[int, int, int, float, str] | None = None  # (starts_with, is_exact, -year_delta, score, model_n)
        for cand_model_n, score, _ in results:
            cand_df = make_df[make_df["model_n"] == cand_model_n]
            if cand_df.empty:
                continue

            starts_with = 1 if _starts_with_query(cand_model_n) else 0

            exact_df = cand_df[cand_df["year"] == year]
            if not exact_df.empty:
                pick = (starts_with, 1, 0, float(score), cand_model_n)
            else:
                nearby_df = cand_df[
                    (cand_df["year"] >= year - 3) &
                    (cand_df["year"] <= year + 3)
                ]
                if nearby_df.empty:
                    continue
                year_delta = int((nearby_df["year"] - year).abs().min())
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

# Subset used for year-based stop-start inference. DIN includes US/Indian makes,
# so this stays conservative to avoid misclassifying non-European vehicles.
_EU_MAKES: frozenset[str] = frozenset({
    "AUDI", "BENTLEY", "BMW", "BRABUS", "CITROEN", "FERRARI", "FIAT",
    "JAGUAR", "LANDROVER", "MERCEDES", "MERCEDES-BENZ", "MINI", "OPEL",
    "PEUGEOT", "PORSCHE", "RENAULT", "ROLLS-ROYCE", "SCANIA", "SKODA",
    "VAUXHALL", "VOLKSWAGEN", "VOLVO",
})

_KOREAN_MAKES: frozenset[str] = frozenset({"HYUNDAI", "KIA"})


def _is_european_make(make: str) -> bool:
    return make.upper().strip() in _EU_MAKES


def _is_korean_make(make: str) -> bool:
    return make.upper().strip() in _KOREAN_MAKES


def _infer_stop_start(make: str, year: Optional[int], fuel: str) -> bool:
    """
    Infer whether a vehicle is likely stop-start equipped based on make + year.
    This is only used when the user does not explicitly tick the stop-start box.
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


def _preferred_tech(
    engine_cc: int,
    fuel: str,
    year: Optional[int],
    make: str,
    stop_start: bool = False,
) -> str:
    """Return the preferred battery technology given engine size and fuel."""
    if fuel == "EV":
        return "MF"
    inferred_stop_start = (not stop_start) and _infer_stop_start(make, year, fuel)
    if stop_start or inferred_stop_start:
        return "AGM"
    if fuel in ("HYBRID",) or (fuel == "PETROL" and 1600 < engine_cc <= 2000):
        return "EFB"
    if fuel == "DIESEL" or engine_cc >= 2500:
        return "AGM"
    return "MF"


# ---------------------------------------------------------------------------
# Data loaders (cached for the lifetime of the process)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _vehicles() -> pd.DataFrame:
    path = os.path.join(_BASE, "vehicle_years.csv")
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip().str.lower()
    df["engine_capacity"] = pd.to_numeric(df["engine_capacity"], errors="coerce")
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    # Normalize keys for robust matching: case-insensitive, trim, and collapse internal whitespace.
    df["make_n"]  = df["make"].astype(str).str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    df["model_n"] = df["model"].astype(str).str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    df["fuel_n"]  = df["fuel"].apply(_norm_fuel)
    return df


@lru_cache(maxsize=1)
def _batteries() -> pd.DataFrame:
    path = os.path.join(_BASE, "battery_specs_output.xlsx")
    df = pd.read_excel(path)
    df.columns = df.columns.str.strip()
    df["Ah"] = pd.to_numeric(df["Ah"], errors="coerce")
    df["CCA (A EN)"] = pd.to_numeric(df["CCA (A EN)"], errors="coerce")
    return df


@lru_cache(maxsize=1)
def _model_aliases() -> pd.DataFrame:
    """
    Optional alias table mapping international model names to JDM model names
    stored in vehicle_years.csv.

    Columns: make, international_model, jdm_model

    Optional columns:
    - priority (int): lower number = more preferred when multiple aliases are viable
    """
    path = os.path.join(_BASE, "model_aliases.csv")
    if not os.path.exists(path):
        return pd.DataFrame(columns=["make_n", "intl_model_n", "jdm_model_n"])

    df = pd.read_csv(path)
    df.columns = df.columns.str.strip().str.lower()
    for col in ("make", "international_model", "jdm_model"):
        if col not in df.columns:
            return pd.DataFrame(columns=["make_n", "intl_model_n", "jdm_model_n"])

    out = pd.DataFrame()
    out["make_n"] = df["make"].astype(str).str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    out["intl_model_n"] = df["international_model"].astype(str).str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    out["jdm_model_n"] = df["jdm_model"].astype(str).str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    if "priority" in df.columns:
        out["priority"] = pd.to_numeric(df["priority"], errors="coerce").fillna(999).astype(int)
    else:
        out["priority"] = 999
    out = out[(out["make_n"] != "") & (out["intl_model_n"] != "") & (out["jdm_model_n"] != "")]
    return out.drop_duplicates()


# ---------------------------------------------------------------------------
# Battery selector
# ---------------------------------------------------------------------------

def _select_batteries(
    target_ah: int,
    preferred_tech: str,
    region: str = "NS",
) -> tuple[dict, list[dict]]:
    """
    Return (primary, alternatives) from battery_specs_output.

    Primary   — best technology match at target_ah within the given region.
    Alternatives — remaining at target_ah + nearest Ah tier above/below,
                   deduplicated by Battery Code, capped at 6.
    Region    — 'NS' (Japanese/Korean/Chinese) or 'DIN' (European/American).
    """
    batt = _batteries()

    # Filter to the correct regional standard first
    batt = batt[batt["Model Key"].apply(lambda k: _battery_region(str(k)) == region)]

    def _row_to_dict(row: pd.Series) -> dict:
        return {
            "battery_code": row["Battery Code"],
            "model_key":    row["Model Key"],
            "ah":           int(row["Ah"]),
            "cca_en":       int(row["CCA (A EN)"]) if pd.notna(row["CCA (A EN)"]) else None,
            "technology":   row["Technology"],
        }

    # Batteries at the exact target Ah
    exact_ah = batt[batt["Ah"] == target_ah]

    # Sort by technology preference
    tech_order = {t: i for i, t in enumerate(_TECH_PRIORITY)}
    exact_sorted = exact_ah.copy()
    exact_sorted["_pref"] = exact_sorted["Technology"].map(
        lambda t: tech_order.get(t, 99)
    )
    exact_sorted = exact_sorted.sort_values("_pref")

    # Primary: preferred tech at target Ah; fall back to best available
    preferred = exact_sorted[exact_sorted["Technology"] == preferred_tech]
    if not preferred.empty:
        primary_row = preferred.iloc[0]
    elif not exact_sorted.empty:
        primary_row = exact_sorted.iloc[0]
    else:
        # No battery at this Ah — find nearest
        nearest_idx = (batt["Ah"] - target_ah).abs().idxmin()
        primary_row = cast(pd.Series, batt.loc[[nearest_idx]].iloc[0])

    primary = _row_to_dict(primary_row)

    # Alternatives: everything else at target Ah
    alt_rows = exact_sorted[exact_sorted["Battery Code"] != primary_row["Battery Code"]]
    alternatives = [_row_to_dict(r) for _, r in alt_rows.iterrows()]

    # Pad alternatives from adjacent Ah tiers if fewer than 3
    if len(alternatives) < 3:
        all_ahs = sorted(batt["Ah"].dropna().unique().tolist())
        # Find the insertion point so we always get true neighbours even when
        # target_ah itself is not in the list (avoids idx=-1 wraparound bug)
        import bisect
        pos = bisect.bisect_left(all_ahs, target_ah)
        neighbour_ahs = []
        if pos < len(all_ahs):
            neighbour_ahs.append(all_ahs[pos] if all_ahs[pos] != target_ah else None)
        if pos > 0:
            neighbour_ahs.append(all_ahs[pos - 1])
        neighbour_ahs = [a for a in neighbour_ahs if a is not None and a != target_ah]
        for neighbour_ah in neighbour_ahs:
            nbr = batt[batt["Ah"] == neighbour_ah]
            for _, r in nbr.iterrows():
                entry = _row_to_dict(r)
                if entry["battery_code"] != primary["battery_code"] and \
                   entry not in alternatives:
                    alternatives.append(entry)
            if len(alternatives) >= 6:
                break

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
    model_n = model.upper().strip()
    subset = df[(df["make_n"] == make_n) & (df["model_n"] == model_n)]
    return sorted(subset["year"].dropna().unique().astype(int).tolist(), reverse=True)


def recommend(
    make: str,
    model: str,
    year: int,
    engine_cc: Optional[int] = None,
    fuel_type: Optional[str] = None,
    enable_aliases: bool = True,
) -> dict:
    df = _vehicles()
    make_n  = make.upper().strip()
    model_n = model.upper().strip()
    model_n = re.sub(r"\s+", " ", model_n)

    resolved_cc:   int  = engine_cc or 1500
    resolved_fuel: str  = _norm_fuel(fuel_type)
    user_provided_cc = engine_cc is not None
    user_provided_fuel = fuel_type is not None and str(fuel_type).strip() != ""
    matched_make:  str | None  = None
    matched_model: str | None  = None
    matched_year:  int | None  = None
    confidence:    int  = 40
    match_type:    str  = "Estimated (Rule-Based)"

    # ── Step 1: filter to the requested make ───────────────────────────
    make_df = df[df["make_n"] == make_n]

    if make_df.empty:
        # Fuzzy fallback for make
        all_makes = df["make_n"].unique().tolist()
        best_make_match = process.extractOne(make_n, all_makes, scorer=fuzz.WRatio)
        if best_make_match and best_make_match[1] >= 75:
            make_n  = best_make_match[0]
            make_df = df[df["make_n"] == make_n]

    # ── Step 2: fuzzy-match the model ──────────────────────────────────
    if not make_df.empty:
        model_choices = make_df["model_n"].dropna().unique().tolist()

        # Prefer exact model-key hits over fuzzy selection. This prevents
        # trim-variant drift where a longer candidate can tie at score=100.
        if model_n in model_choices:
            best_model = (model_n, 100.0)
        else:
            best_model = _fuzzy_model_score_for_year(model_n, make_df, int(year))

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
                    cand_df = make_df[make_df["model_n"] == cand_model_n]
                    exact_df = cand_df[cand_df["year"] == year]
                    if not exact_df.empty:
                        pick = (1, 0, -int(alias_priority), jdm_score, cand_model_n)
                        if best_pick is None or pick > best_pick:
                            best_pick = pick
                        continue

                    nearby_df = cand_df[
                        (cand_df["year"] >= year - 3) &
                        (cand_df["year"] <= year + 3)
                    ]
                    if nearby_df.empty:
                        continue
                    year_delta = int((nearby_df["year"] - year).abs().min())
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
    pref_tech = _preferred_tech(resolved_cc, resolved_fuel, effective_year, make_n, False)
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
        "primary":        primary,
        "alternatives":   alternatives,
    }
