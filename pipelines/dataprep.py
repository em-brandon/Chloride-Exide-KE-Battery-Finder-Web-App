"""
dataprep.py — CRSP Excel → vehicles_raw table + CSV

Can be run standalone:
    python pipelines/dataprep.py data/My-CRSP-File.xlsx

Or called programmatically:
    from pipelines.dataprep import main
    result = main("data/My-CRSP-File.xlsx", log_callback=..., progress_callback=...)
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Callable, Optional

import pandas as pd


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_years(year_value) -> list[int]:
    if pd.isna(year_value):
        return []
    match = re.findall(r"\d{4}", str(year_value))
    return [int(y) for y in match] if match else []


def split_batteries(battery_value) -> list[str]:
    if pd.isna(battery_value):
        return []
    battery_value = str(battery_value).upper()
    parts = re.split(r"[\/,;]", battery_value)
    return [p.strip().replace(" ", "") for p in parts if p.strip()]


def normalize_battery(battery: str) -> str:
    return battery.upper().replace(" ", "") if battery else ""


# ── Main callable ─────────────────────────────────────────────────────────────

def main(
    input_file: str,
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    cancel_event=None,
) -> dict:
    """
    Process a CRSP Excel file and write to vehicles_raw + CSV output.

    Args:
        input_file:         Path to the source Excel file.
        log_callback:       Called with a log line string at each stage.
        progress_callback:  Called with (stage_name, current, total).
        cancel_event:       threading.Event; if set mid-run, processing stops early.

    Returns:
        dict with keys: total_rows, clean_rows, rejected, duplicates, output_csv
    """

    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    def progress(stage: str, current: int, total: int) -> None:
        if progress_callback:
            progress_callback(stage, current, total)

    def cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    input_path = Path(input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    output_csv   = str(input_path.parent / "battery_lookup_dataset.csv")
    output_excel = str(input_path.parent / "battery_lookup_dataset.xlsx")

    # ── Stage 1: Load ─────────────────────────────────────────────────────────
    log(f"[STAGE] Loading dataset: {input_path.name}")
    progress("Loading", 0, 1)
    t0 = time.time()
    df = pd.read_excel(input_file)
    log(f"[OK] Loaded {len(df)} rows in {time.time()-t0:.2f}s")
    progress("Loading", 1, 1)

    if cancelled():
        return {"status": "cancelled"}

    # ── Stage 2: Clean columns ────────────────────────────────────────────────
    log("[STAGE] Cleaning column names")
    progress("Schema", 0, 1)
    df.columns = df.columns.str.strip().str.lower().str.replace(r'[\s\n]+', '_', regex=True)
    log(f"[OK] Columns: {df.columns.tolist()}")

    required_cols = ["make", "model"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    progress("Schema", 1, 1)

    if cancelled():
        return {"status": "cancelled"}

    # ── Stage 3: Normalize ────────────────────────────────────────────────────
    log("[STAGE] Normalizing fields")
    output_cols       = ["make", "model", "model_number", "engine_capacity", "fuel"]
    present_cols      = [c for c in output_cols if c in df.columns]
    total_rows        = len(df)
    rows              = []
    rejected          = 0
    rejected_rows: list[dict] = []
    MAX_REJECTED_DETAIL = 200

    for idx, (_, row) in enumerate(df.iterrows(), start=1):
        if cancelled():
            return {"status": "cancelled"}

        record = {c: str(row.get(c, "")).strip() for c in present_cols}
        if not record.get("make") or record["make"].lower() == "nan":
            rejected += 1
            if len(rejected_rows) < MAX_REJECTED_DETAIL:
                rejected_rows.append({
                    "row_number": idx,
                    "make":       record.get("make", ""),
                    "model":      record.get("model", ""),
                    "reason":     "empty_make",
                })
            continue
        if record.get("fuel", "").lower() == "electric":
            rejected += 1
            if len(rejected_rows) < MAX_REJECTED_DETAIL:
                rejected_rows.append({
                    "row_number": idx,
                    "make":       record.get("make", ""),
                    "model":      record.get("model", ""),
                    "reason":     "electric_vehicle",
                })
            continue
        rows.append(record)

        if idx % 500 == 0 or idx == total_rows:
            progress("Normalizing", idx, total_rows)
            log(f"[PROGRESS] Normalized {idx}/{total_rows} rows")

    log(f"[OK] {len(rows)} valid rows, {rejected} rejected")
    progress("Normalizing", total_rows, total_rows)

    # ── Stage 4: Deduplicate ──────────────────────────────────────────────────
    log("[STAGE] Deduplicating")
    progress("Dedup", 0, 1)
    final_df   = pd.DataFrame(rows, columns=present_cols)
    before_ded = len(final_df)
    final_df   = final_df.drop_duplicates()
    duplicates = before_ded - len(final_df)
    final_df   = final_df.sort_values(by=["make", "model"])
    log(f"[OK] {duplicates} duplicates removed → {len(final_df)} clean rows")
    progress("Dedup", 1, 1)

    if cancelled():
        return {"status": "cancelled"}

    # ── Stage 5: Write output ─────────────────────────────────────────────────
    log(f"[STAGE] Saving output to {output_csv}")
    progress("Saving", 0, 2)
    final_df.to_csv(output_csv, index=False, encoding='utf-8')
    log(f"[OK] CSV saved: {output_csv}")
    progress("Saving", 1, 2)
    final_df.to_excel(output_excel, index=False)
    log(f"[OK] Excel saved: {output_excel}")
    progress("Saving", 2, 2)

    log(f"[DONE] Final record count: {len(final_df)}")

    return {
        "status":        "done",
        "total_rows":    total_rows,
        "clean_rows":    len(final_df),
        "rejected":      rejected,
        "duplicates":    duplicates,
        "output_csv":    output_csv,
        "columns_found": present_cols,
        "rejected_rows": rejected_rows,
    }


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <path/to/CRSP.xlsx>")
        sys.exit(1)
    result = main(sys.argv[1])
    print(result)
