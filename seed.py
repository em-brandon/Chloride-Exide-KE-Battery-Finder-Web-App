"""
seed.py — One-time data loader.

Reads existing CSV / Excel flat files and inserts all records into the
PostgreSQL database created by the Alembic migration.

Run once after `alembic upgrade head`:

    python seed.py

Safe to re-run — each table is truncated before re-inserting, so you get a
clean load every time. Use this to refresh data when the source files change.

Source files
------------
vehicle_years.csv          → vehicle_years  (primary runtime table)
battery_specs_output.xlsx  → battery_specs
model_aliases.csv          → model_aliases
battery_lookup_dataset.csv → vehicles_raw   (staging / intermediate)
"""

from __future__ import annotations

import os
import sys
import time

import pandas as pd
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Ensure project root is on path when run directly.
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from db import engine, Base          # noqa: E402
from models import (                 # noqa: E402  — registers models on metadata
    VehicleRaw,
    VehicleYear,
    BatterySpec,
    ModelAlias,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(f"[seed] {msg}", flush=True)


def _truncate(table_name: str, conn) -> None:
    conn.execute(text(f'TRUNCATE TABLE "{table_name}" RESTART IDENTITY CASCADE'))
    _log(f"Truncated {table_name}")


def _bulk_insert(df: pd.DataFrame, table_name: str, conn, chunk_size: int = 1000) -> int:
    """Insert a DataFrame in chunks using core INSERT statements. Returns row count."""
    rows = df.to_dict(orient="records")
    total = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        conn.execute(Base.metadata.tables[table_name].insert(), chunk)
        total += len(chunk)
    return total


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def seed_vehicle_years(conn) -> None:
    path = os.path.join(ROOT, "vehicle_years.csv")
    if not os.path.exists(path):
        _log(f"SKIP vehicle_years — {path} not found")
        return

    _log("Loading vehicle_years.csv …")
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip().str.lower()

    df = df.rename(columns={"engine_capacity": "engine_capacity"})  # no-op, explicit
    df["engine_capacity"] = pd.to_numeric(df["engine_capacity"], errors="coerce")
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["make", "model", "year"])
    df["year"] = df["year"].astype(int)
    # Convert NaN → None so psycopg2 inserts NULL instead of NaN
    df["engine_capacity"] = df["engine_capacity"].astype(object).where(df["engine_capacity"].notna(), other=None)
    df["fuel"] = df["fuel"].astype(object).where(df["fuel"].notna(), other=None)

    # Keep only the columns the table expects
    df = df[["make", "model", "year", "engine_capacity", "fuel"]].drop_duplicates(
        subset=["make", "model", "year"]
    )

    _truncate("vehicle_years", conn)
    n = _bulk_insert(df, "vehicle_years", conn)
    _log(f"Inserted {n:,} rows into vehicle_years")


def seed_battery_specs(conn) -> None:
    path = os.path.join(ROOT, "battery_specs_output.xlsx")
    if not os.path.exists(path):
        _log(f"SKIP battery_specs — {path} not found")
        return

    _log("Loading battery_specs_output.xlsx …")
    df = pd.read_excel(path)
    df.columns = df.columns.str.strip()

    # Map Excel column names → DB column names
    rename = {
        "Battery Code": "battery_code",
        "Model Key":    "model_key",
        "Ah":           "ah",
        "CCA (A EN)":   "cca_en",
        "Technology":   "technology",
    }
    missing = [c for c in rename if c not in df.columns]
    if missing:
        _log(f"ERROR: battery_specs_output.xlsx is missing columns: {missing}")
        sys.exit(1)

    df = df[list(rename.keys())].rename(columns=rename)
    df["ah"] = pd.to_numeric(df["ah"], errors="coerce")
    df["cca_en"] = pd.to_numeric(df["cca_en"], errors="coerce")
    df = df.dropna(subset=["battery_code", "model_key"])
    df = df.drop_duplicates(subset=["battery_code"])

    # Convert NaN → None so psycopg2 inserts NULL instead of NaN
    df["ah"]     = df["ah"].astype(object).where(df["ah"].notna(),     other=None)
    df["cca_en"] = df["cca_en"].astype(object).where(df["cca_en"].notna(), other=None)
    df["technology"] = df["technology"].astype(object).where(df["technology"].notna(), other=None)

    _truncate("battery_specs", conn)
    n = _bulk_insert(df, "battery_specs", conn)
    _log(f"Inserted {n:,} rows into battery_specs")


def seed_model_aliases(conn) -> None:
    path = os.path.join(ROOT, "model_aliases.csv")
    if not os.path.exists(path):
        _log(f"SKIP model_aliases — {path} not found")
        return

    _log("Loading model_aliases.csv …")
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip().str.lower()

    required = ["make", "international_model", "jdm_model"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        _log(f"ERROR: model_aliases.csv is missing columns: {missing}")
        sys.exit(1)

    if "priority" not in df.columns:
        df["priority"] = 999
    df["priority"] = pd.to_numeric(df["priority"], errors="coerce").fillna(999).astype(int)

    df = df[["make", "international_model", "jdm_model", "priority"]].drop_duplicates(
        subset=["make", "international_model", "jdm_model"]
    )

    _truncate("model_aliases", conn)
    n = _bulk_insert(df, "model_aliases", conn)
    _log(f"Inserted {n:,} rows into model_aliases")


def seed_vehicles_raw(conn) -> None:
    path = os.path.join(ROOT, "battery_lookup_dataset.csv")
    if not os.path.exists(path):
        _log(f"SKIP vehicles_raw — {path} not found")
        return

    _log("Loading battery_lookup_dataset.csv …")
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip().str.lower()

    # Normalise column names from dataprep.py output
    col_map: dict[str, str] = {}
    for col in df.columns:
        if "engine" in col and "cap" in col:
            col_map[col] = "engine_capacity"
        elif col in ("model_number", "model_no", "modelnumber"):
            col_map[col] = "model_number"

    if col_map:
        df = df.rename(columns=col_map)

    keep = ["make", "model"]
    for optional in ("model_number", "engine_capacity", "fuel"):
        if optional in df.columns:
            keep.append(optional)
    df = df[keep].copy()

    for c in ("model_number", "engine_capacity", "fuel"):
        if c not in df.columns:
            df[c] = None

    df["engine_capacity"] = pd.to_numeric(df["engine_capacity"], errors="coerce")
    df = df.dropna(subset=["make", "model"])
    df = df.drop_duplicates(subset=["make", "model", "engine_capacity", "fuel"])
    # Convert NaN → None so psycopg2 inserts NULL instead of NaN
    df["engine_capacity"] = df["engine_capacity"].astype(object).where(df["engine_capacity"].notna(), other=None)
    df["model_number"] = df["model_number"].astype(object).where(df["model_number"].notna(), other=None)
    df["fuel"] = df["fuel"].astype(object).where(df["fuel"].notna(), other=None)

    _truncate("vehicles_raw", conn)
    n = _bulk_insert(df, "vehicles_raw", conn)
    _log(f"Inserted {n:,} rows into vehicles_raw")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    t0 = time.time()
    _log("Starting seed — connecting to database …")

    # Create all tables if they don't exist yet (idempotent safety net).
    # In production you should rely on `alembic upgrade head` instead.
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        seed_vehicle_years(conn)
        seed_battery_specs(conn)
        seed_model_aliases(conn)
        seed_vehicles_raw(conn)

    elapsed = time.time() - t0
    _log(f"Seed complete in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
