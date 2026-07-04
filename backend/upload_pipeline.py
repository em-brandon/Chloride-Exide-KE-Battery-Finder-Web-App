"""
upload_pipeline.py — Excel battery data cleanup and upsert pipeline.

Entry point
-----------
    result = process_battery_upload(file_bytes, db, changed_by)

Validation rules (per row)
--------------------------
- battery_code : non-blank string           (REQUIRED)
- model_key    : non-blank string           (REQUIRED)
- ah           : numeric float, > 0         (REQUIRED)
- cca_en       : numeric float if present   (OPTIONAL — may be blank/null)
- technology   : non-blank string           (REQUIRED)

Any row missing a required field, or with a type error, is REJECTED.
Valid rows are committed regardless; the caller receives a full report.

Merge rules (on battery_code conflict)
---------------------------------------
- Not in DB        → INSERT  + audit log
- In DB, identical → SKIP    (no write)
- In DB, different → UPDATE  + audit log (full overwrite; all fields
                               guaranteed non-null at this point)
- Duplicate battery_code within the file → last occurrence wins, warning logged
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from models import BatteryAuditLog, BatterySpec

logger = logging.getLogger("battery_finder.upload")

# ---------------------------------------------------------------------------
# Column name aliases accepted in the uploaded file
# ---------------------------------------------------------------------------
_COL_ALIASES: dict[str, str] = {
    # battery_code variants
    "battery_code": "battery_code",
    "batterycode":  "battery_code",
    "code":         "battery_code",
    "sku":          "battery_code",
    # model_key variants
    "model_key":    "model_key",
    "modelkey":     "model_key",
    "model":        "model_key",
    # ah variants
    "ah":           "ah",
    "capacity_ah":  "ah",
    "capacity":     "ah",
    # cca_en variants
    "cca_en":       "cca_en",
    "cca":          "cca_en",
    "cold_crank":   "cca_en",
    # technology variants
    "technology":   "technology",
    "tech":         "technology",
    "type":         "technology",
    "battery_type": "technology",
}

REQUIRED_FIELDS = ["battery_code", "model_key", "ah", "technology"]
ALL_FIELDS      = REQUIRED_FIELDS + ["cca_en"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RowError:
    row: int
    battery_code: str
    reason: str


@dataclass
class UploadResult:
    inserted:           int = 0
    updated:            int = 0
    skipped_unchanged:  int = 0
    rejected:           int = 0
    errors:             list[RowError] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip, lowercase, and remap column names using _COL_ALIASES."""
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    df = df.rename(columns=_COL_ALIASES)
    return df


def _validate_row(row_num: int, raw: dict) -> tuple[Optional[dict], Optional[RowError]]:
    """
    Validate and normalize a single row dict.
    Returns (clean_dict, None) on success or (None, RowError) on failure.
    """
    missing: list[str] = []

    # --- battery_code ---
    battery_code = str(raw.get("battery_code", "")).strip().upper()
    if not battery_code:
        missing.append("battery_code")

    # --- model_key ---
    model_key = str(raw.get("model_key", "")).strip().upper()
    if not model_key:
        missing.append("model_key")

    # --- ah ---
    ah_raw = raw.get("ah", None)
    ah: Optional[float] = None
    ah_error: Optional[str] = None
    if ah_raw is None or str(ah_raw).strip() == "" or str(ah_raw).strip().lower() == "nan":
        missing.append("ah")
    else:
        try:
            ah = float(ah_raw)
            if ah <= 0:
                ah_error = f"ah must be > 0, got {ah}"
        except (ValueError, TypeError):
            ah_error = f"ah is not numeric: {ah_raw!r}"

    # --- technology ---
    technology = str(raw.get("technology", "")).strip().upper()
    if not technology or technology == "NAN":
        missing.append("technology")

    # --- cca_en (optional) ---
    cca_raw = raw.get("cca_en", None)
    cca_en: Optional[float] = None
    cca_error: Optional[str] = None
    if cca_raw is not None and str(cca_raw).strip() not in ("", "nan", "NaN", "None"):
        try:
            cca_en = float(cca_raw)
        except (ValueError, TypeError):
            cca_error = f"cca_en is not numeric: {cca_raw!r}"

    # Collect errors
    reasons: list[str] = []
    if missing:
        reasons.append(f"missing required fields: {missing}")
    if ah_error:
        reasons.append(ah_error)
    if cca_error:
        reasons.append(cca_error)

    if reasons:
        return None, RowError(
            row=row_num,
            battery_code=battery_code or "(blank)",
            reason="; ".join(reasons),
        )

    return {
        "battery_code": battery_code,
        "model_key":    model_key,
        "ah":           ah,
        "cca_en":       cca_en,
        "technology":   technology,
    }, None


def _battery_to_dict(b: BatterySpec) -> dict:
    return {
        "battery_code": b.battery_code,
        "model_key":    b.model_key,
        "ah":           b.ah,
        "cca_en":       b.cca_en,
        "technology":   b.technology,
    }


def _write_audit(
    db: Session,
    battery_id: Optional[int],
    action: str,
    changed_by: str,
    old: Optional[dict],
    new: Optional[dict],
) -> None:
    log = BatteryAuditLog(
        battery_id=battery_id,
        action=action,
        changed_by=changed_by,
        changed_at=datetime.now(timezone.utc),
        old_values=json.dumps(old) if old else None,
        new_values=json.dumps(new) if new else None,
    )
    db.add(log)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_battery_upload(
    file_bytes: bytes,
    db: Session,
    changed_by: str,
) -> UploadResult:
    """
    Parse *file_bytes* as an Excel (.xlsx) file, validate every row,
    and upsert valid rows into battery_specs.

    Parameters
    ----------
    file_bytes  : raw bytes of the uploaded .xlsx file
    db          : active SQLAlchemy session
    changed_by  : admin username, stored in the audit log

    Returns
    -------
    UploadResult with counts and per-row errors.
    """
    result = UploadResult()

    # ------------------------------------------------------------------
    # 1. Parse Excel
    # ------------------------------------------------------------------
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    except Exception as exc:
        raise ValueError(f"Could not parse Excel file: {exc}") from exc

    if df.empty:
        raise ValueError("Uploaded file contains no rows.")

    df = _normalize_columns(df)

    # Check that at least the required columns exist after remapping
    missing_cols = [c for c in REQUIRED_FIELDS if c not in df.columns]
    if missing_cols:
        raise ValueError(
            f"File is missing required columns after normalization: {missing_cols}. "
            f"Columns found: {list(df.columns)}"
        )

    # ------------------------------------------------------------------
    # 2. Validate rows + deduplicate within file (last occurrence wins)
    # ------------------------------------------------------------------
    seen_codes: dict[str, int] = {}   # battery_code → last valid row index
    clean_rows: dict[int, dict] = {}  # row_num → clean dict
    warned_dupes: set[str] = set()

    for i, raw_row in enumerate(df.to_dict(orient="records"), start=2):  # row 1 = header
        clean, error = _validate_row(i, raw_row)
        if error:
            result.rejected += 1
            result.errors.append(error)
            continue

        code = clean["battery_code"]  # type: ignore[index]
        if code in seen_codes:
            if code not in warned_dupes:
                logger.warning(
                    "Duplicate battery_code %r in upload file. "
                    "Row %d overwrites row %d.",
                    code, i, seen_codes[code],
                )
                warned_dupes.add(code)
            # Remove previous occurrence so last wins
            del clean_rows[seen_codes[code]]

        seen_codes[code] = i
        clean_rows[i] = clean  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # 3. Upsert valid rows
    # ------------------------------------------------------------------
    # Load all existing battery codes in one query for efficiency
    existing: dict[str, BatterySpec] = {
        b.battery_code: b
        for b in db.query(BatterySpec).filter(BatterySpec.deleted_at.is_(None)).all()
    }

    for clean in clean_rows.values():
        code = clean["battery_code"]
        existing_battery = existing.get(code)

        if existing_battery is None:
            # INSERT
            new_battery = BatterySpec(
                battery_code=clean["battery_code"],
                model_key=clean["model_key"],
                ah=clean["ah"],
                cca_en=clean["cca_en"],
                technology=clean["technology"],
            )
            db.add(new_battery)
            db.flush()  # populate new_battery.id
            _write_audit(db, new_battery.id, "INSERT", changed_by, None, clean)
            result.inserted += 1

        else:
            old = _battery_to_dict(existing_battery)
            # Compare all fields to decide INSERT vs SKIP
            changed = (
                existing_battery.model_key  != clean["model_key"]
                or existing_battery.ah      != clean["ah"]
                or existing_battery.cca_en  != clean["cca_en"]
                or existing_battery.technology != clean["technology"]
            )
            if not changed:
                result.skipped_unchanged += 1
                continue

            # UPDATE
            existing_battery.model_key  = clean["model_key"]
            existing_battery.ah         = clean["ah"]
            existing_battery.cca_en     = clean["cca_en"]
            existing_battery.technology = clean["technology"]
            _write_audit(db, existing_battery.id, "UPDATE", changed_by, old, clean)
            result.updated += 1

    db.commit()
    return result
