"""
Clean the Dial-A-Battery 2023-2026 order export and load it into
batteryfinderdev as the dial_battery_inference table.

Run once (or whenever the spreadsheet is refreshed):
    python dial_battery_clean.py
"""

import re
import sys
import os
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import engine

EXCEL_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "Dial-A-Battery Data - 2023-2026.xlsx")
SHEET_NAME = "Dial A Battery Orders"
TABLE_NAME = "dial_battery_inference"


def _strip_qty(val: str) -> str:
    """Remove leading quantity digit(s): '2 NS70MFL POWERLAST' -> 'NS70MFL POWERLAST'."""
    return re.sub(r"^\d+\s+", "", str(val).strip())


def clean() -> pd.DataFrame:
    print(f"Loading '{EXCEL_PATH}' …")
    raw = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME)

    # Keep the four useful columns; drop everything else
    df = raw[["Vehicle Type", "Vehicle Model", "Batteries", "Created On"]].copy()

    # Parse the sale date; coerce unparseable values to NaT
    df["Created On"] = pd.to_datetime(df["Created On"], errors="coerce")

    # Drop rows missing the three required text fields
    before = len(df)
    df = df.dropna(subset=["Vehicle Type", "Vehicle Model", "Batteries"])
    print(f"  Dropped {before - len(df)} rows with null values -> {len(df)} remaining")

    # Expand comma-separated multi-battery rows into individual rows
    # e.g. "1 NS70MFL POWERLAST, 1 NS70MFR POWERLAST" -> two rows
    df["Batteries"] = df["Batteries"].astype(str).str.split(",")
    df = df.explode("Batteries").reset_index(drop=True)

    # Strip leading quantity digit from each battery value
    df["Batteries"] = df["Batteries"].str.strip().apply(_strip_qty)

    # Normalize all text: uppercase + collapse internal whitespace
    for col in ["Vehicle Type", "Vehicle Model", "Batteries"]:
        df[col] = (
            df[col]
            .astype(str)
            .str.upper()
            .str.strip()
            .str.replace(r"\s+", " ", regex=True)
        )

    # Drop any rows that are empty after cleaning
    df = df[
        (df["Batteries"].str.len() > 0)
        & (df["Vehicle Type"].str.len() > 0)
        & (df["Vehicle Model"].str.len() > 0)
    ]

    # Deduplicate raw rows (case already handled by uppercase above)
    before = len(df)
    df = df.drop_duplicates(subset=["Vehicle Type", "Vehicle Model", "Batteries", "Created On"])
    print(f"  Dropped {before - len(df)} duplicate rows -> {len(df)} remaining")

    # Aggregate: frequency = number of orders; last_sale_date = most recent order date
    agg = (
        df.groupby(["Vehicle Type", "Vehicle Model", "Batteries"])
        .agg(
            frequency=("Created On", "count"),
            last_sale_date=("Created On", "max"),
        )
        .reset_index()
    )
    agg = agg.rename(columns={
        "Vehicle Type": "vehicle_type",
        "Vehicle Model": "vehicle_model",
        "Batteries": "battery_code",
    })
    agg = agg.sort_values("frequency", ascending=False).reset_index(drop=True)

    print(f"  {len(agg)} unique (make, model, battery) combinations after aggregation")
    return agg


def load(df: pd.DataFrame) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {TABLE_NAME} RESTART IDENTITY"))

    df.to_sql(TABLE_NAME, engine, if_exists="append", index=False)
    print(f"Loaded {len(df)} rows into '{TABLE_NAME}'")


if __name__ == "__main__":
    df = clean()
    load(df)
    print("Done.")
