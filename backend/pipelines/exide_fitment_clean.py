"""
Clean the Exide global fitment guide ('EXIDE BATTERY FINDER' Excel, repo root)
and load it into batteryfinderdev as two tables:

  - oem_fitment         Ah/technology fitment specs, kept as year-ranges.
  - vehicle_years_exide  make/model/year existence rows, exploded from those
                         ranges so they're searchable (unioned with
                         vehicle_years by matcher._vehicles()).

vehicle_years itself is NEVER written to — this script only ever writes to
its own two tables, both fully truncate+reloaded on every run (like
dial_battery_clean.py).

Run once (or whenever Exide sends an updated catalog):
    python pipelines/exide_fitment_clean.py
"""

import os
import re
import sys
import unicodedata

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import engine
from dataprep import strip_redundant_make_prefix

EXCEL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "EXIDE BATTERY FINDER - 01.09.2025 (2).xlsx")
CURRENT_YEAR = 2026
MAX_REJECTED_DETAIL = 200

# ── Make canonicalization ───────────────────────────────────────────────────
# Not a filter — makes with no existing vehicle_years counterpart pass through
# unchanged (that's the intended coverage expansion). This only bridges
# spelling drift for makes that already exist, so a real make doesn't
# fragment into two dropdown entries (e.g. "VW" and "VOLKSWAGEN").
_MAKE_ALIASES = {
    "LAND ROVER": "LANDROVER",
    "FUSO (MITSUBISHI)": "MITSUBISHI FUSO",
    "UD NISSAN DIESEL": "NISSAN DIESEL/UD",
    "UD TRUCKS": "NISSAN DIESEL/UD",
    "VW": "VOLKSWAGEN",
}

# ── Technology cleaning ──────────────────────────────────────────────────────
# Only confidently-identifiable typos/synonyms are fixed. Tier-name values
# (PREMIUM/CLASSIC/START PRO/POWER PRO/STANDARD) look like Exide product
# lines rather than battery chemistry and are left as-is — collapsing them
# into EFB/MF/AGM/GEL would need real Exide product knowledge nobody has
# right now. raw_technology always preserves the pre-fix value.
_TECH_FIXES = {
    "AAG": "AGM",
    "POWER PPRO": "POWER PRO",
    "SMF": "MF",   # Sealed Maintenance-Free — defensible chemistry synonym
    "CC": None,
    "FX": None,
    "AE": None,
    "C": None,
}

_YEAR_RANGE_RE = re.compile(r"^(\d{4})\s*-{1,2}\s*(\d{4}|PRESENT)$", re.IGNORECASE)
_NUMERIC_RE = re.compile(r"^\d+(\.\d+)?$")
_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)?\s*$")  # trailing "(...)" or unclosed "(..."


def _clean_make(raw) -> str:
    if pd.isna(raw):
        return ""
    s = str(raw).strip().upper()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s).strip()
    return _MAKE_ALIASES.get(s, s)


def _clean_technology(raw) -> tuple[str | None, str | None]:
    """Returns (cleaned, raw_upper_stripped)."""
    if pd.isna(raw):
        return None, None
    s = str(raw).strip().upper()
    if not s:
        return None, None
    return _TECH_FIXES.get(s, s), s


def _fix_passenger_orientation(ah_raw, type_raw):
    """
    ~40% of the PASSENGER CARS sheet has Battery Capacity (Ah) and Battery
    Type swapped (verified: 38,618/96,224 rows). Whichever of the two cells
    is numeric is the real Ah value; whichever is alphabetic is the real
    technology value — detected per row, not trusted from the header.

    Returns (ah_value, technology_value, swapped: bool, unresolved: bool).
    """
    ah_s = "" if pd.isna(ah_raw) else str(ah_raw).strip()
    type_s = "" if pd.isna(type_raw) else str(type_raw).strip()
    ah_is_num = bool(_NUMERIC_RE.match(ah_s))
    type_is_num = bool(_NUMERIC_RE.match(type_s))

    if type_is_num and not ah_is_num:
        return type_raw, ah_raw, True, False
    if ah_s and type_s and not ah_is_num and not type_is_num:
        return None, None, False, True
    return ah_raw, type_raw, False, False


def _parse_year_range(raw) -> tuple[int, int | None] | None:
    """Returns (year_from, year_to) where year_to=None means open-ended."""
    if pd.isna(raw):
        return None
    s = str(raw).strip()
    if not s:
        return None

    m = _YEAR_RANGE_RE.match(s)
    if m:
        y1 = int(m.group(1))
        y2_raw = m.group(2)
        y2 = None if y2_raw.upper() == "PRESENT" else int(y2_raw)
    else:
        runs = re.findall(r"\d{4}", s)
        if not runs:
            return None
        y1 = int(runs[0])
        if len(runs) > 1:
            y2 = int(runs[1])
        elif "PRESENT" in s.upper():
            y2 = None
        else:
            y2 = y1

    if y2 is not None and y2 < y1:
        y1, y2 = y2, y1
    if y1 < 1900 or y1 > CURRENT_YEAR + 1:
        return None
    if y2 is not None and (y2 - y1 > 100):
        return None
    return y1, y2


def _parse_cylinder_cc(raw) -> int | None:
    if pd.isna(raw):
        return None
    digits = re.sub(r"[^\d]", "", str(raw))
    if not digits:
        return None
    val = int(digits)
    return val if val > 0 else None


def _strip_chassis_code_suffix(model: str) -> str:
    """Strip a trailing '(...)' chassis-code block for display purposes,
    e.g. 'ABARTH 500/595/695 1.4( 312.AXF1A, 312.AD1A' -> '500/595/695 1.4'.
    Handles unclosed parens (seen in the source data)."""
    stripped = _TRAILING_PAREN_RE.sub("", model).strip()
    return stripped if stripped else model


def _clean_sheet(vehicle_category: str, raw: pd.DataFrame, ah_col: int, type_col: int) -> tuple[list[dict], dict]:
    """
    Shared cleaning for one sheet. ah_col/type_col are positional indices
    (not names) — PASSENGER and COMMERCIAL have Ah/Type in different
    physical column order, and PASSENGER's model column is unlabeled, so
    everything here is accessed by position, verified once against the
    actual file rather than trusted from pandas' auto-generated headers.

    Columns (both sheets, by position): 0=make, 1=model, 2=year,
    ah_col=Ah, type_col=Type, 5=dimensions, 6=cylinder_capacity.
    """
    stats = {
        "total": len(raw),
        "swapped": 0,
        "rejected": 0,
        "rejected_rows": [],
        "reasons": {},
    }

    def reject(row_number, make, model, reason):
        stats["rejected"] += 1
        stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
        if len(stats["rejected_rows"]) < MAX_REJECTED_DETAIL:
            stats["rejected_rows"].append({
                "row_number": row_number,
                "sheet": vehicle_category,
                "make": make,
                "model": model,
                "reason": reason,
            })

    cols = raw.columns
    out: list[dict] = []

    for idx, row in enumerate(raw.itertuples(index=False), start=1):
        make_raw = row[0]
        model_raw = row[1]
        year_raw = row[2]
        ah_raw = row[ah_col]
        type_raw = row[type_col]
        dim_raw = row[5]
        cc_raw = row[6]

        make = _clean_make(make_raw)
        if not make:
            reject(idx, make_raw, model_raw, "empty_make")
            continue

        model_raw_str = "" if pd.isna(model_raw) else str(model_raw).strip()
        model = strip_redundant_make_prefix(make, model_raw_str)

        year_range = _parse_year_range(year_raw)
        if year_range is None:
            reject(idx, make, model, "unparseable_year" if pd.notna(year_raw) else "empty_year")
            continue
        year_from, year_to = year_range

        if vehicle_category == "passenger":
            ah_val, tech_val, swapped, unresolved = _fix_passenger_orientation(ah_raw, type_raw)
            if swapped:
                stats["swapped"] += 1
            if unresolved:
                reject(idx, make, model, "unresolvable_ah_type_orientation")
                continue
        else:
            ah_val, tech_val = ah_raw, type_raw

        ah_s = "" if pd.isna(ah_val) else str(ah_val).strip()
        ah = float(ah_s) if _NUMERIC_RE.match(ah_s) else None
        technology, raw_technology = _clean_technology(tech_val)
        cylinder_capacity_cc = _parse_cylinder_cc(cc_raw)

        if ah is None and technology is None and cylinder_capacity_cc is None:
            reject(idx, make, model, "no_ah_no_tech_no_cc")
            continue

        out.append({
            "vehicle_category": vehicle_category,
            "make": make,
            "model": model,
            "year_from": year_from,
            "year_to": year_to,
            "ah": ah,
            "technology": technology,
            "raw_technology": raw_technology,
            "dimensions": None if pd.isna(dim_raw) else str(dim_raw).strip(),
            "cylinder_capacity_cc": cylinder_capacity_cc,
            "source_row": idx,
        })

    return out, stats


def clean() -> tuple[pd.DataFrame, pd.DataFrame]:
    print(f"Loading '{EXCEL_PATH}' …")

    passenger_raw = pd.read_excel(EXCEL_PATH, sheet_name="PASSENGER CARS", header=1)
    passenger_raw = passenger_raw.dropna(subset=[passenger_raw.columns[0]])
    commercial_raw = pd.read_excel(EXCEL_PATH, sheet_name="COMMERCIAL VEHICLES", header=1)
    commercial_raw = commercial_raw.dropna(subset=[commercial_raw.columns[0]])

    print(f"  PASSENGER CARS: {len(passenger_raw)} rows, COMMERCIAL VEHICLES: {len(commercial_raw)} rows")

    # PASSENGER: Make(0), Model(1), Year(2), Ah(3), Type(4), Dimensions(5), CC(6)
    passenger_rows, passenger_stats = _clean_sheet("passenger", passenger_raw, ah_col=3, type_col=4)
    # COMMERCIAL: Make(0), Model(1), Year(2), Type(3), Ah(4), Dimensions(5), CC(6)
    commercial_rows, commercial_stats = _clean_sheet("commercial", commercial_raw, ah_col=4, type_col=3)

    for label, stats in (("PASSENGER CARS", passenger_stats), ("COMMERCIAL VEHICLES", commercial_stats)):
        print(f"  [{label}] {stats['total'] - stats['rejected']} kept, {stats['rejected']} rejected, "
              f"{stats['swapped']} Ah/Type swaps fixed")
        for reason, count in stats["reasons"].items():
            print(f"    - {reason}: {count}")

    all_rows = passenger_rows + commercial_rows
    fitment_df = pd.DataFrame(all_rows, columns=[
        "vehicle_category", "make", "model", "year_from", "year_to",
        "ah", "technology", "raw_technology", "dimensions",
        "cylinder_capacity_cc", "source_row",
    ])

    before = len(fitment_df)
    fitment_df = fitment_df.drop_duplicates(
        subset=["make", "model", "vehicle_category", "year_from", "year_to", "ah", "technology"],
        keep="first",
    )
    print(f"  Deduplicated fitment rows: {before} -> {len(fitment_df)}")

    # ── Explode into vehicle_years_exide (existence rows for the matcher/dropdowns) ──
    vy_rows: list[dict] = []
    for r in all_rows:
        y1 = r["year_from"]
        y2 = min(r["year_to"], CURRENT_YEAR) if r["year_to"] is not None else CURRENT_YEAR
        model_display = _strip_chassis_code_suffix(r["model"])
        for year in range(y1, y2 + 1):
            vy_rows.append({
                "make": r["make"],
                "model": model_display,
                "year": year,
                "engine_capacity": r["cylinder_capacity_cc"],
                "fuel": None,
            })

    vy_df = pd.DataFrame(vy_rows, columns=["make", "model", "year", "engine_capacity", "fuel"])
    before = len(vy_df)
    vy_df = vy_df.drop_duplicates(subset=["make", "model", "year"], keep="first")
    print(f"  Exploded vehicle_years_exide candidates: {before} -> {len(vy_df)} after dedup")

    return fitment_df, vy_df


def load(fitment_df: pd.DataFrame, vy_df: pd.DataFrame) -> None:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE oem_fitment RESTART IDENTITY"))
    fitment_df.to_sql("oem_fitment", engine, if_exists="append", index=False)
    print(f"Loaded {len(fitment_df)} rows into 'oem_fitment'")

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE vehicle_years_exide RESTART IDENTITY"))
    vy_df.to_sql("vehicle_years_exide", engine, if_exists="append", index=False)
    print(f"Loaded {len(vy_df)} rows into 'vehicle_years_exide'")


if __name__ == "__main__":
    fitment_df, vy_df = clean()
    load(fitment_df, vy_df)
    print("Done. Restart the app or POST /api/admin/cache/refresh to pick up the new data.")
