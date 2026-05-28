"""
Fill missing CCA (A EN) values in battery_specs using standard NS/JIS and DIN specifications.

Standard values sourced from JIS D 5301 and EN 50342-1.
Run once (or after adding new batteries):
    python fill_cca.py

Only updates rows where cca_en IS NULL — never overwrites existing values.
Prints a summary of what was updated.
"""

import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import SessionLocal
from models import BatterySpec

# ---------------------------------------------------------------------------
# Standard CCA lookup tables
# Keys are battery code prefixes / exact patterns matched against
# battery_spec.battery_code (case-insensitive, whitespace-normalised).
# ---------------------------------------------------------------------------

# NS/JIS standard CCA (A EN).
# Matched by extracting the JIS size code from the battery_code string.
_NS_CCA: dict[str, int] = {
    # Compact / small cars
    "NS40":    300,
    "NS40S":   300,
    "NS40Z":   330,
    "NS40ZS":  330,
    "NS50":    360,
    "NS50Z":   390,
    "NS55":    390,
    "NS55D23": 430,
    # Mid-size
    "NS60":    390,
    "NS60S":   390,
    "NS60Z":   430,
    "NS60ZS":  430,
    "NS65":    430,
    "NS70":    470,
    "NS70L":   470,
    "NS70R":   470,
    "NS70MF":  470,
    "NS70MFL": 470,
    "NS70MFR": 470,
    "NS70ZMF": 500,
    # D-series (larger JIS)
    "55D23":   430,
    "65D23":   480,
    "75D23":   540,
    "80D23":   560,
    "85D23":   580,
    "NS80D26": 590,
    "NS90D26": 590,
    "80D26":   590,
    "90D26":   620,
    "95D26":   640,
    "100D26":  660,
    # E/F/G series (trucks, SUVs, buses)
    "105D31":  700,
    "115D31":  760,
    "130E41":  820,
    "135E41":  850,
    "145G51":  900,
    "NS100D31": 700,
    "NS110D31": 750,
    "NS120D31": 800,
    # N-series heavy-duty (JIS C 8704 / truck & bus batteries)
    "N50":    430,
    "N50Z":   460,
    "N55":    480,
    "N70":    540,
    "N70Z":   570,
    "N100":   750,
    "N120":   850,
    "N150":   950,
    "N180":  1050,
    "N200":  1150,
    "N220":  1250,
}

# DIN/IEC standard CCA (A EN).
# Matched by extracting the Ah number from the battery_code (e.g. DIN 55 -> 55Ah -> 520 CCA).
_DIN_CCA: dict[int, int] = {
    # Ah -> typical CCA EN
    35:  300,
    40:  330,
    40:  360,
    43:  410,
    44:  420,
    45:  400,
    50:  450,
    52:  470,
    55:  520,
    60:  540,
    61:  600,
    62:  580,
    63:  600,
    65:  620,
    66:  640,
    70:  640,
    72:  680,
    74:  680,
    75:  700,
    77:  700,
    80:  740,
    88:  800,
    90:  840,
    92:  850,
    95:  850,
    100: 900,
    105: 950,
    110: 950,
    115: 1000,
    120: 1000,
}


def _extract_ns_cca(code: str) -> int | None:
    """Match the battery code against known NS/JIS sizes."""
    c = re.sub(r"\s+", "", code.upper())
    # Try longest prefix match first (e.g. NS70MFL before NS70)
    for key in sorted(_NS_CCA, key=len, reverse=True):
        if c.startswith(key.replace(" ", "")):
            return _NS_CCA[key]
    return None


def _extract_din_cca(code: str, ah: float | None) -> int | None:
    """For DIN batteries, map Ah to CCA. Fall back to parsing digits from code."""
    target_ah: int | None = None
    if ah is not None:
        target_ah = int(round(ah))
    else:
        # Try to extract Ah from DIN code, e.g. "DIN 60" or "DIN60MF"
        m = re.search(r"(\d{2,3})", code)
        if m:
            target_ah = int(m.group(1))
    if target_ah is not None and target_ah in _DIN_CCA:
        return _DIN_CCA[target_ah]
    return None


def fill_missing_cca() -> None:
    db = SessionLocal()
    try:
        missing = (
            db.query(BatterySpec)
            .filter(BatterySpec.cca_en.is_(None))
            .filter(BatterySpec.deleted_at.is_(None))
            .all()
        )

        if not missing:
            print("No batteries with missing CCA — nothing to update.")
            return

        print(f"Found {len(missing)} batteries with NULL cca_en. Filling…\n")

        updated = 0
        skipped = 0

        for spec in missing:
            code = (spec.battery_code or "").strip().upper()
            mk = (spec.model_key or "").strip().upper()

            # Determine NS vs DIN from model_key prefix
            is_din = mk.startswith("DIN")

            cca: int | None = None
            if is_din:
                cca = _extract_din_cca(code, spec.ah)
            else:
                cca = _extract_ns_cca(code)
                if cca is None:
                    # Fall back to DIN lookup for unrecognised codes
                    cca = _extract_din_cca(code, spec.ah)

            if cca is not None:
                print(f"  {spec.battery_code:<30}  {spec.ah}Ah  ->  {cca} CCA")
                spec.cca_en = float(cca)
                updated += 1
            else:
                print(f"  {spec.battery_code:<30}  {spec.ah}Ah  ->  (no match, skipped)")
                skipped += 1

        db.commit()
        print(f"\nUpdated {updated} rows. Skipped {skipped} (no standard match).")

    finally:
        db.close()


if __name__ == "__main__":
    fill_missing_cca()
