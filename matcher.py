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
from functools import lru_cache
from typing import Optional

import pandas as pd
from rapidfuzz import process, fuzz

_BASE = os.path.dirname(os.path.abspath(__file__))

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


def _target_ah(engine_cc: int, fuel: str) -> int:
    for max_cc, p_ah, d_ah, h_ah in _AH_RULES:
        if engine_cc <= max_cc:
            if fuel == "DIESEL":
                return d_ah
            if fuel == "HYBRID":
                return h_ah
            return p_ah
    return 100


# ---------------------------------------------------------------------------
# Technology preference per Ah + fuel
# Priority order (highest first): EFB, AGM, MF, SB (Flooded)
# ---------------------------------------------------------------------------

_TECH_PRIORITY = ["EFB", "AGM", "MF", "SB (Flooded)"]


def _preferred_tech(engine_cc: int, fuel: str, stop_start: bool = False) -> str:
    """Return the preferred battery technology given engine size, fuel, and stop-start.

    Stop-start (i-Stop) forces a minimum of EFB. Diesel stop-start or large
    displacement stop-start requires AGM for the extra cycle durability.
    """
    if fuel == "EV":
        return "MF"
    if stop_start:
        # Diesel stop-start or large-engine stop-start → AGM mandatory
        if fuel == "DIESEL" or engine_cc >= 2500:
            return "AGM"
        # Petrol / hybrid stop-start → EFB minimum
        return "EFB"
    if fuel == "HYBRID" or (fuel == "PETROL" and 1600 < engine_cc <= 2000):
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
    df["make_n"]  = df["make"].str.upper().str.strip()
    df["model_n"] = df["model"].str.upper().str.strip()
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


# ---------------------------------------------------------------------------
# Battery selector
# ---------------------------------------------------------------------------

def _select_batteries(
    target_ah: int,
    preferred_tech: str,
) -> tuple[dict, list[dict]]:
    """
    Return (primary, alternatives) from battery_specs_output.

    Primary   — best technology match at target_ah.
    Alternatives — remaining at target_ah + nearest Ah tier above/below,
                   deduplicated by Battery Code, capped at 6.
    """
    batt = _batteries()

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
        primary_row = batt.loc[nearest_idx]

    primary = _row_to_dict(primary_row)

    # Alternatives: everything else at target Ah
    alt_rows = exact_sorted[exact_sorted["Battery Code"] != primary_row["Battery Code"]]
    alternatives = [_row_to_dict(r) for _, r in alt_rows.iterrows()]

    # Pad alternatives from adjacent Ah tiers if fewer than 3
    if len(alternatives) < 3:
        all_ahs = sorted(batt["Ah"].dropna().unique().tolist())
        idx = all_ahs.index(target_ah) if target_ah in all_ahs else -1
        for neighbour_ah in ([all_ahs[idx + 1]] if idx < len(all_ahs) - 1 else []) + \
                            ([all_ahs[idx - 1]] if idx > 0 else []):
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


def recommend(
    make: str,
    model: str,
    year: int,
    engine_cc: Optional[int] = None,
    fuel_type: Optional[str] = None,
    has_stop_start: bool = False,
) -> dict:
    df = _vehicles()
    make_n  = make.upper().strip()
    model_n = model.upper().strip()

    resolved_cc:   int  = engine_cc or 1500
    resolved_fuel: str  = _norm_fuel(fuel_type)
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
        model_choices = make_df["model_n"].unique().tolist()
        best_model = process.extractOne(model_n, model_choices, scorer=fuzz.WRatio)

        if best_model and best_model[1] >= 60:
            matched_model_n = best_model[0]
            model_score     = best_model[1]
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
                resolved_cc   = int(row["engine_capacity"]) if pd.notna(row["engine_capacity"]) else resolved_cc
                resolved_fuel = _norm_fuel(str(row["fuel"])) if pd.notna(row.get("fuel")) else resolved_fuel

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
                    resolved_cc   = int(nearest["engine_capacity"]) if pd.notna(nearest["engine_capacity"]) else resolved_cc
                    resolved_fuel = _norm_fuel(str(nearest["fuel"])) if pd.notna(nearest.get("fuel")) else resolved_fuel

    # ── Step 4: compute target Ah + technology preference ──────────────
    target_ah    = _target_ah(resolved_cc, resolved_fuel)
    pref_tech    = _preferred_tech(resolved_cc, resolved_fuel, stop_start=has_stop_start)
    primary, alternatives = _select_batteries(target_ah, pref_tech)

    return {
        "make":           make_n,
        "model":          model_n,
        "year":           year,
        "engine_cc":      resolved_cc,
        "fuel_type":      resolved_fuel,
        "has_stop_start": has_stop_start,
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
