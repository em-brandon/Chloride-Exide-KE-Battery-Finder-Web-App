import time
import re

import pandas as pd

# =========================
# CONFIG
# =========================
INPUT_XLSX = "NTSA Vehicles Registered 2024.xlsx"
SHEET_NAME = "Table1"
OUTPUT_CSV = "nts_vehicles_clean.csv"
OUTPUT_EXCEL = "nts_vehicles_clean.xlsx"

# Column names as present in the input workbook
COL_MAKE = "Make"
COL_MODEL = "Model"
COL_YEAR = "Year of Manufacture"

LOG_EVERY_N_ROWS = 5000


def log_section(title: str) -> float:
    print(f"\n[START] {title}")
    return time.time()


def end_section(start_time: float, title: str) -> None:
    elapsed = time.time() - start_time
    print(f"[END] {title} | Time taken: {elapsed:.2f}s")


def _clean_make(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


_ws_re = re.compile(r"\s+")


def _clean_model(value) -> str:
    if pd.isna(value):
        return ""
    s = str(value).strip()
    s = _ws_re.sub(" ", s)
    return s


def _clean_year(value):
    if pd.isna(value):
        return None
    try:
        # Excel often reads years as floats like 2022.0
        y = int(float(value))
    except Exception:
        # Last-ditch: extract a 4-digit year
        m = re.search(r"(19\d{2}|20\d{2})", str(value))
        if not m:
            return None
        y = int(m.group(1))
    # Basic sanity range
    if y < 1950 or y > 2100:
        return None
    return y


def main() -> None:
    start = log_section("Loading NTS Excel")
    df = pd.read_excel(INPUT_XLSX, sheet_name=SHEET_NAME)
    end_section(start, "Loading NTS Excel")

    start = log_section("Selecting and normalizing columns")

    required = [COL_MAKE, COL_MODEL, COL_YEAR]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise Exception(f"Missing required columns in {INPUT_XLSX}/{SHEET_NAME}: {missing}")

    df = df[required].copy()

    # Clean values
    df["make"] = df[COL_MAKE].map(_clean_make)
    df["model"] = df[COL_MODEL].map(_clean_model)
    df["year"] = df[COL_YEAR].map(_clean_year)

    # Drop invalid rows
    before = len(df)
    df = df[(df["make"] != "") & (df["model"] != "") & (df["year"].notna())]
    df["year"] = df["year"].astype(int)
    after = len(df)
    print(f"Rows kept after basic validation: {after}/{before}")

    # Keep minimal schema
    df = df[["make", "model", "year"]]

    # Drop duplicates
    before_dupes = len(df)
    df = df.drop_duplicates(subset=["make", "model", "year"]).reset_index(drop=True)
    after_dupes = len(df)
    print(f"Duplicates removed: {before_dupes - after_dupes}")

    # Sort for stable diffs
    df = df.sort_values(by=["make", "model", "year"]).reset_index(drop=True)

    end_section(start, "Selecting and normalizing columns")

    start = log_section("Saving cleaned outputs")
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"CSV saved: {OUTPUT_CSV} ({len(df)} rows)")

    try:
        df.to_excel(OUTPUT_EXCEL, index=False)
        print(f"Excel saved: {OUTPUT_EXCEL}")
    except Exception as e:
        print(f"Excel output skipped: {e}")

    end_section(start, "Saving cleaned outputs")

    print("\nProcess complete")


if __name__ == "__main__":
    main()
