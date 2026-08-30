"""
xlsx_to_mysql.py
----------------
Turn the business workbook (Battery-Fitment-Data.xlsx) into a MySQL 8 database.

WHY THIS EXISTS
---------------
export_fitment_workbook.py writes a spreadsheet: good for a reader, awkward for
anyone who wants to query the data or load it somewhere else. This script takes
that same workbook and produces a real relational database, so the dataset is
portable independently of Excel and of this project's Postgres.

WHAT IT DROPS
-------------
Three columns are presentation, not data, and are removed on the way in:

  Capacity source              (Web Validated Fitments) a per-row provenance
                               label computed at export time.
  Vehicle type                 (OEM Fitment Guide) reference-only category.
  Applies to our makes/years   (OEM Fitment Guide) exists purely so a reader can
                               filter the sheet down to the makes we trade in.

Each is asserted present before being dropped — a silently-missing column would
mean shipping data the caller asked to have removed.

WHY IT EMITS SQL INSTEAD OF CONNECTING
--------------------------------------
No MySQL driver is installed (pymysql/mysqlclient), and adding one to the split
requirements files for a one-off conversion isn't worth it. Writing a UTF-8 .sql
file and piping it into the server's own mysql client is also the most reliable
route on Windows for the ~4,000 OEM model names that contain non-ASCII text.

Usage (run from backend/)
-------------------------
    python scripts/xlsx_to_mysql.py --out load.sql

    docker exec -i battery-fitment-mysql mysql -uroot -pPASS < load.sql
    docker exec battery-fitment-mysql mysqldump -uroot -pPASS \
        --databases battery_fitment --default-character-set=utf8mb4 \
        --single-transaction > ../Battery-Fitment-Data.sql
"""

from __future__ import annotations

import argparse
import os
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

DB_NAME = "battery_fitment"

# The workbook puts a title row and an explanatory paragraph above the headers,
# so the real header line is the third row on both data sheets.
HEADER_ROW = 2

# Rows per INSERT statement. Large enough that 110k rows load in seconds, small
# enough to stay well under max_allowed_packet.
BATCH = 1000

WEB_SHEET = "Web Validated Fitments"
OEM_SHEET = "OEM Fitment Guide"

WEB_TABLE = "web_validated_fitments"
OEM_TABLE = "oem_fitment_guide"

# (sheet header, column name, SQL type). Order here is the column order in the
# table, and deliberately mirrors the order of the columns in the workbook.
WEB_COLUMNS = [
    ("Make", "make", "VARCHAR(32) NOT NULL"),
    ("Model", "model", "VARCHAR(128) NOT NULL"),
    ("Year", "year", "SMALLINT UNSIGNED NOT NULL"),
    ("Engine size (cc)", "engine_size_cc", "INT UNSIGNED NULL"),
    ("Fuel", "fuel", "VARCHAR(20) NOT NULL"),
    ("Recommended battery", "recommended_battery", "VARCHAR(64) NOT NULL"),
    ("Capacity (Ah)", "capacity_ah", "SMALLINT UNSIGNED NOT NULL"),
    ("Battery type", "battery_type", "VARCHAR(8) NOT NULL"),
]
WEB_DROP = ["Capacity source"]

OEM_COLUMNS = [
    ("Make", "make", "VARCHAR(32) NOT NULL"),
    ("Model", "model", "VARCHAR(160) NULL"),
    ("Fits from", "fits_from", "SMALLINT UNSIGNED NOT NULL"),
    ("Fits until", "fits_until", "SMALLINT UNSIGNED NULL"),
    ("Capacity (Ah)", "capacity_ah", "SMALLINT UNSIGNED NULL"),
    ("Battery type", "battery_type", "VARCHAR(16) NULL"),
    ("Dimensions", "dimensions", "VARCHAR(24) NULL"),
    ("Engine size (cc)", "engine_size_cc", "INT UNSIGNED NULL"),
]
OEM_DROP = ["Vehicle type", "Applies to our makes/years"]

WEB_KEYS = [
    "PRIMARY KEY (id)",
    # No duplicates exist on this triple in the source, so the unique key both
    # holds and documents the grain of the sheet. A rejection here on a future
    # workbook is a real finding about the data, not a reason to drop the key.
    "UNIQUE KEY uq_make_model_year (make, model, year)",
    "KEY idx_make_model (make, model)",
]
OEM_KEYS = [
    "PRIMARY KEY (id)",
    "KEY idx_make_model (make, model)",
    "KEY idx_years (fits_from, fits_until)",
    "KEY idx_capacity (capacity_ah)",
]

NUMERIC_TYPES = ("INT", "SMALLINT", "BIGINT", "TINYINT")


def sql_str(value: str) -> str:
    """Quote a string for MySQL, escaping what its parser cares about."""
    out = (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\x1a", "\\Z")
    )
    return "'" + out + "'"


def sql_value(value, is_numeric: bool) -> str:
    """Render one cell as a SQL literal.

    pandas reads an integer column as float the moment it contains a blank, and
    a missing value arrives here as NaN — which is truthy and stringifies to the
    literal text "nan". Both have to be handled explicitly, or the database ends
    up holding 1400.0 and "nan".
    """
    if value is None or pd.isna(value):
        return "NULL"
    if is_numeric:
        return str(int(round(float(value))))
    text = str(value).strip()
    return "NULL" if text == "" else sql_str(text)


def load_sheet(xlsx: str, sheet: str, columns, drop) -> pd.DataFrame:
    df = pd.read_excel(xlsx, sheet_name=sheet, header=HEADER_ROW)

    absent = [c for c in drop if c not in df.columns]
    if absent:
        raise SystemExit(
            "[%s] cannot drop %s — not present. Found: %s"
            % (sheet, absent, list(df.columns))
        )
    df = df.drop(columns=drop)

    absent = [src for src, _, _ in columns if src not in df.columns]
    if absent:
        raise SystemExit("[%s] expected column(s) absent: %s" % (sheet, absent))

    df = df[[src for src, _, _ in columns]]
    df.columns = [name for _, name, _ in columns]
    print("[%s] %s rows, %d columns (dropped: %s)"
          % (sheet, format(len(df), ","), len(df.columns), ", ".join(drop)))
    return df


def emit_table(fh, table: str, df: pd.DataFrame, columns, keys) -> None:
    coldefs = ["  id INT UNSIGNED NOT NULL AUTO_INCREMENT"]
    coldefs += ["  %s %s" % (name, sqltype) for _, name, sqltype in columns]
    coldefs += ["  %s" % k for k in keys]

    fh.write("DROP TABLE IF EXISTS %s;\n" % table)
    fh.write("CREATE TABLE %s (\n" % table)
    fh.write(",\n".join(coldefs))
    fh.write("\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 "
             "COLLATE=utf8mb4_unicode_ci;\n\n")

    numeric = [sqltype.split()[0] in NUMERIC_TYPES for _, _, sqltype in columns]
    names = ", ".join(name for _, name, _ in columns)
    prefix = "INSERT INTO %s (%s) VALUES\n" % (table, names)

    def flush(batch):
        fh.write(prefix)
        fh.write(",\n".join(batch))
        fh.write(";\n")

    batch = []
    written = 0
    for row in df.itertuples(index=False, name=None):
        batch.append(
            "(" + ",".join(sql_value(v, n) for v, n in zip(row, numeric)) + ")"
        )
        if len(batch) >= BATCH:
            flush(batch)
            written += len(batch)
            batch = []
    if batch:
        flush(batch)
        written += len(batch)
    fh.write("\n")
    print("[%s] wrote %s rows" % (table, format(written, ",")))


def main() -> None:
    root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    ap = argparse.ArgumentParser(description="Convert the fitment workbook to MySQL.")
    ap.add_argument("--xlsx", default=os.path.join(root, "Battery-Fitment-Data.xlsx"))
    ap.add_argument("--out", required=True,
                    help="path for the generated .sql load file")
    args = ap.parse_args()

    if not os.path.exists(args.xlsx):
        raise SystemExit("workbook not found: %s" % args.xlsx)

    web = load_sheet(args.xlsx, WEB_SHEET, WEB_COLUMNS, WEB_DROP)
    oem = load_sheet(args.xlsx, OEM_SHEET, OEM_COLUMNS, OEM_DROP)

    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("-- Generated by backend/scripts/xlsx_to_mysql.py\n")
        fh.write("-- Source: %s\n\n" % os.path.basename(args.xlsx))
        fh.write("SET NAMES utf8mb4;\n")
        fh.write("SET autocommit = 0;\n")
        fh.write("SET unique_checks = 0;\n\n")
        fh.write("CREATE DATABASE IF NOT EXISTS %s\n"
                 "  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n" % DB_NAME)
        fh.write("USE %s;\n\n" % DB_NAME)
        emit_table(fh, WEB_TABLE, web, WEB_COLUMNS, WEB_KEYS)
        emit_table(fh, OEM_TABLE, oem, OEM_COLUMNS, OEM_KEYS)
        fh.write("COMMIT;\n")
        fh.write("SET unique_checks = 1;\n")

    size = os.path.getsize(args.out) / 1024 / 1024
    print("\nwrote %s (%.1f MB)" % (args.out, size))


if __name__ == "__main__":
    main()
