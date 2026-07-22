"""
Clean the Exide global fitment guide ('EXIDE BATTERY FINDER' Excel, repo root)
and load it into batteryfinderdev's oem_fitment table (Ah/technology fitment
specs, kept as year-ranges) — full truncate+reload on every run (like
dial_battery_clean.py). vehicle_years itself is NEVER written to.

vehicle_years_exide (make/model/year existence rows, unioned with
vehicle_years by matcher._vehicles() so both are searchable) is a live SQL
VIEW computed directly from oem_fitment (see migration
convert_vehicle_years_exide_to_view) — it updates automatically whenever
oem_fitment changes, by this script or otherwise, with no separate
load/refresh step.

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

# Below this, an Ah value is a small AGM backup/auxiliary battery for a
# stop-start system (real form factors like 97*43*58, 150*90*105mm — verified
# against source rows), not the vehicle's primary starter battery. Exide's
# sheet lists both for some models; this app only ever recommends the
# primary battery, so these rows are dropped rather than kept with a
# misleadingly tiny Ah.
MIN_AH = 20.0

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
    # Regional divisions of a make we already carry — fold into the parent
    # rather than let them fragment into separate dropdown entries.
    "FORD ASIA & OCEANIA": "FORD",
    "FORD AUSTRALIA": "FORD",
    "FORD OTOSAN": "FORD",
    "FORD USA": "FORD",
    "ISUZU( JIANGXI)": "ISUZU",
    "PEUGEOT (DF-PSA)": "PEUGEOT",
    "MAHINDRA GUJARAT": "MAHINDRA",
    "MERCEDEZ-BENZ": "MERCEDES-BENZ",  # typo variant in the source file
    "KG MOBILITY": "SSANGYONG",        # SsangYong's post-2023 corporate rename
}

# ── Kenya-market relevance filter ───────────────────────────────────────────
# Exide's file is a GLOBAL catalog (365 distinct makes after cleaning) —
# most were never sold in Kenya/Uganda/Tanzania. Rather than keep every
# defunct/vintage/hypercar/farm-equipment/foreign-haulage brand searchable
# in the app, makes with essentially zero plausibility in this market are
# dropped here. This is a deliberate, reviewed exclusion (not silent) —
# see the make-by-category breakdown in the PR/commit this shipped with.
# Not applied to _MAKE_ALIASES targets above (those fold into a kept make).
_EXCLUDED_MAKES: frozenset[str] = frozenset({
    # Farm/agricultural equipment & tractors — not road vehicles at all.
    "AGCO", "ALLGAIER", "ARMATRAC", "BASAK", "BAUTZ", "BCS", "BELARUS",
    "BM TRACTORS", "BUCHER", "CARRARO", "CASE IH", "CHALLENGER", "CLAAS",
    "DEUTZ-FAHR", "FAHR", "FENDT", "FERRARI AGRI", "GINAF", "GOLDONI",
    "GUELDNER", "HATTAT", "JCB FASTTRAC", "JOHN DEERE", "KIOTI", "KRAMER",
    "LANDINI", "MASSEY FERGUSON", "MCCORMICK", "NEW HOLLAND", "PASQUALI",
    "PFANZELT", "SAME", "STEYR", "VALTRA", "ZETOR",
    # Foreign buses/coaches — Kenya's PSV fleet runs on Isuzu/Hino/Scania/
    # MAN/Mitsubishi Fuso chassis, all already covered as existing makes.
    "ALEXANDER DENNIS", "BERKHOF", "BOVA", "BREDAMENARINIBUS", "DROGMOLLER",
    "HEULIEZ", "HIGER", "INBUS", "IRISBUS", "IRIZAR", "KAROSA", "KAVZ",
    "KING LONG", "LAZ", "MARBUS", "NEOPLAN", "OPTARE", "OTOKAR", "PLAXTON",
    "SETRA", "SOLARIS", "TEMSA", "TERBERG-BENSCHOP", "TROLIGA BUS",
    "VAN HOOL", "VDL", "WRIGHT", "YUTONG", "BYD ADL",
    # Foreign heavy-haulage trucks — same logic as buses.
    "ASHOK LEYLAND", "AVIA", "BHARATBENZ", "DAF", "DENNIS", "ERF", "FAP",
    "FODEN TRUCKS", "FREIGHTLINER", "GAZ", "IVECO", "JIEFANG", "KAMAZ",
    "KARSAN", "KENWORTH", "LEYLAND", "MACK", "MAGIRUS-DEUTZ", "MAZ",
    "MAZ-MAN", "MIULTICAR", "MULTICAR", "OAF", "RENAULT TRUCKS",
    "ROSENBAUER", "SHAANXI", "SHACMAN", "SINOTRUK (CNHTC)", "SISU", "STAR",
    "TATRA", "UAZ", "URAL", "WESTERN STAR",
    # Defunct/vintage/classic — discontinued, mostly pre-1990s.
    "AC", "AMC", "ASKAM", "AUSTIN", "AUSTIN-HEALEY", "AUTO UNION",
    "AUTOBIANCHI", "AUTOZAM", "BARKAS", "BRISTOL", "CHECKER", "DAIMLER",
    "DALLAS", "DE LOREAN", "DE TOMASO", "EMW", "EUNOS", "FSO", "GALLOPER",
    "GEO", "GIOTTI VICTORIA", "GLAS", "HILLMAN", "HINDUSTAN", "HOBBYCAR",
    "ICKX", "INDIGO", "INNOCENTI", "ISDERA", "IZH", "JENSEN", "LADA",
    "LANCIA", "METROCAB", "MIDDLEBRIDGE", "MORRIS", "MOSKVICH", "NSU",
    "OLDSMOBILE", "OLTCIT", "PANTHER", "PLYMOUTH", "PONTIAC", "PREMIER",
    "RAYTON FISSORE", "RELIANT", "RILEY", "SAAB", "SANTANA", "SAO",
    "STANDARD AUTOMOBILE", "SUNBEAM", "TALBOT", "TRABANT", "TRIUMPH",
    "WARTBURG", "WOLSELEY", "YUGO", "ZATAVA", "ZAZ",
    # Ultra-luxury/hypercar/exotic — not a realistic retail battery search.
    "ALPINA", "ARIEL", "ARTEGA", "ASTON MARTIN", "BAC", "BITTER",
    "BIZZARRINI", "BUGATTI", "CALLAWAY", "CATERHAM", "FERRARI", "GINETTA",
    "KOENIGSEGG", "LAMBORGHINI", "LOTUS", "LTI", "MARCOS", "MASERATI",
    "MAYBACH", "MCLAREN", "MCW", "MORGAN", "NOBLE", "PAGANI", "PANOZ",
    "PININFARINA", "RUF", "SHELBY", "SPECTRE", "SPYKER", "TVR", "VECTOR",
    "VUHL", "WESTFIELD", "WIESMANN",
    # Niche microcars / low-speed EVs — no Kenya presence.
    "AIXAM", "CHATENET", "DS( CAPSA)", "DSK", "DURSO", "EBRO", "EMC",
    "EVO", "MICRO", "MICROCAR", "STREETSCOOTER", "THINK",
    # Chinese/new-energy brands with no real Kenya import channel today.
    # Kept: BYD, MG, GEELY, FOTON, JAC (Chery/Great Wall/Haval already
    # existed before this pipeline ran).
    "BAIC", "BEIJING", "BESTUNE", "BRILLIANCE", "DFSK", "DONGFENG XIAOKANG",
    "FENGON", "GENESIS", "LANDWIND", "LEAPMOTOR", "LIFAN", "LIVAN",
    "LYNK & CO", "MAXUS", "OMODA", "POLESTAR", "SERES", "SHINERAY", "SMART",
    "TOFAS", "VOYAH", "WEITUO", "WEY", "YUEJIN", "YULON",
    # Second-pass review — caught after the first exclusion pass shipped:
    # more of the same categories above (defunct/obscure, foreign farm/bus/
    # truck equipment, microcars/kit-cars, coachbuilders/tuners) that were
    # missed when the set above was first written.
    "AEBI", "AL-GHAZI", "ALVIS", "AMW", "ARO", "ASIA MOTORS", "ASTRA",
    "AYATS", "BAM", "BEDFORD", "BERTONE", "BMC", "BOND", "BORGWARD",
    "BRANSON", "CARBODIES", "CARON", "CMC", "DONKERVOORT", "DR", "FISKER",
    "FPV", "GRUAU", "GULERYUZ", "HICOM", "HSV", "INTERNATIONAL HARV",
    "IRMSCHER", "KA", "LEVC", "LIGIER", "MEGA", "MINELLI", "MITSUOKA",
    "MPM MOTORS", "MWM", "OSCA", "PADANE", "PEGASO", "POLARIS", "PUCH",
    "RANGER", "SIPANI", "SML", "SPORTEQUIPE", "SWM MOTORS", "UMM",
    "VISEON", "VOLVO BM", "YAGMUR", "ZENOS CARS",
})

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
        if make in _EXCLUDED_MAKES:
            reject(idx, make, model_raw, "excluded_make_not_kenya_relevant")
            continue

        model_raw_str = "" if pd.isna(model_raw) else str(model_raw).strip().upper()
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

        if ah is not None and ah < MIN_AH:
            reject(idx, make, model, "ah_below_starter_battery_min")
            continue

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

    # Collapse near-duplicate rows: same make/model/year-range/technology/dimensions
    # (i.e. the same physical battery slot) with Ah differing by <=5 — verified
    # against real rows to be rounding/typo noise from the source sheet (identical
    # dimensions, adjacent source_row), not genuine distinct tiers. Keep the
    # highest Ah. Groups with a bigger gap (>=10 Ah, same dimensions) are left
    # alone — those are real economy/premium tier options Exide actually sells.
    group_cols = ["make", "model", "year_from", "year_to", "technology", "dimensions"]
    ah_hi = fitment_df.groupby(group_cols, dropna=False)["ah"].transform("max")
    ah_lo = fitment_df.groupby(group_cols, dropna=False)["ah"].transform("min")
    before = len(fitment_df)
    is_near_dup_loser = fitment_df["ah"].notna() & ((ah_hi - ah_lo) <= 5) & (fitment_df["ah"] < ah_hi)
    fitment_df = fitment_df.loc[~is_near_dup_loser].reset_index(drop=True)
    print(f"  Collapsed near-duplicate Ah rows (delta<=5, same dimensions, keep highest): {before} -> {len(fitment_df)}")

    # vehicle_years_exide (existence rows for the matcher/dropdowns) is a live
    # SQL VIEW computed directly from oem_fitment (see migration
    # convert_vehicle_years_exide_to_view) — it always reflects the current
    # table with no separate explode/load step needed here.
    return fitment_df


def load(fitment_df: pd.DataFrame) -> None:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE oem_fitment RESTART IDENTITY"))
    fitment_df.to_sql("oem_fitment", engine, if_exists="append", index=False)
    print(f"Loaded {len(fitment_df)} rows into 'oem_fitment'")


if __name__ == "__main__":
    fitment_df = clean()
    load(fitment_df)
    print("Done. vehicle_years_exide is a view, so it updates automatically. "
          "Restart the app or POST /api/admin/cache/refresh to pick up the new data.")
