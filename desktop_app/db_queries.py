"""All DB read/write operations for the desktop app."""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from sqlalchemy import text

from db import engine, SessionLocal


# ── Coverage ──────────────────────────────────────────────────────────────────

def get_coverage() -> dict:
    """Mirrors admin_router.py coverage logic."""
    from matcher import _norm_model_key

    with engine.connect() as conn:
        vy = pd.read_sql(
            "SELECT make, model, year, engine_capacity, fuel FROM vehicle_years",
            conn,
        )
        wbv = pd.read_sql(
            "SELECT make_n, model_n, year FROM web_battery_validation",
            conn,
        )
        master_count = conn.execute(
            text("SELECT COUNT(*) FROM web_battery_validation")
        ).scalar() or 0
        staging_count = conn.execute(
            text("SELECT COUNT(*) FROM web_battery_staging")
        ).scalar() or 0

    if vy.empty:
        total = matched = 0
        pct = 0.0
        unmatched_vehicles: list[dict] = []
        total_buckets = resolved_buckets = remaining_buckets = 0
    else:
        vy["model_n"] = vy["model"].apply(_norm_model_key)
        vy["make_n"]  = vy["make"].str.upper().str.strip()
        combos = vy[["make_n", "model_n", "year"]].drop_duplicates()
        total = len(combos)

        if not wbv.empty:
            wbv["make_n"]  = wbv["make_n"].str.upper().str.strip()
            wbv["model_n"] = wbv["model_n"].apply(_norm_model_key)
            merged = combos.merge(wbv, on=["make_n", "model_n", "year"], how="left", indicator=True)
            matched = int((merged["_merge"] == "both").sum())
        else:
            merged = combos.copy()
            merged["_merge"] = "left_only"
            matched = 0

        unmatched = merged[merged["_merge"] == "left_only"][["make_n", "model_n", "year"]].copy()
        unmatched_vehicles = unmatched.rename(columns={"make_n": "make", "model_n": "model"}).to_dict("records")

        pct = round(matched / total * 100, 1) if total else 0.0

        # Year-bucket coverage
        combos2 = combos.copy()
        combos2["bucket"] = (combos2["year"] // 5) * 5
        wbv2 = wbv.copy() if not wbv.empty else pd.DataFrame(columns=["make_n", "model_n", "year"])
        wbv2["bucket"] = (wbv2["year"] // 5) * 5
        total_buckets    = combos2["bucket"].nunique()
        resolved_buckets = wbv2["bucket"].nunique()
        remaining_buckets = max(0, total_buckets - resolved_buckets)

    cache_path = Path(__file__).resolve().parent.parent / "cache" / "web_model_cache.json"
    try:
        web_cache_size = len(json.loads(cache_path.read_text(encoding="utf-8")))
    except Exception:
        web_cache_size = 0

    return {
        "total": total,
        "matched": matched,
        "unmatched": total - matched,
        "pct_matched": pct,
        "master_count": master_count,
        "staging_count": staging_count,
        "unmatched_vehicles": unmatched_vehicles,
        "total_buckets": total_buckets,
        "resolved_buckets": resolved_buckets,
        "remaining_buckets": remaining_buckets,
        "web_cache_size": web_cache_size,
    }


# ── Staging ───────────────────────────────────────────────────────────────────

STAGING_FILTERS = ("all", "valid", "invalid", "conflicts")


def get_staging(page: int = 1, filter_: str = "all", page_size: int = 50) -> dict:
    offset = (page - 1) * page_size
    where_clauses = {
        "all":       "",
        "valid":     "WHERE is_valid = TRUE AND (conflict IS NULL OR conflict = FALSE)",
        "invalid":   "WHERE is_valid = FALSE",
        "conflicts": "WHERE conflict = TRUE",
    }
    where = where_clauses.get(filter_, "")

    with engine.connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM web_battery_staging {where}")
        ).scalar() or 0
        rows = conn.execute(
            text(
                f"SELECT id, make_n, model_n, year, battery_code, ah, technology, "
                f"source, engine_cc, fuel_type, staged_at, is_valid, invalid_reason, "
                f"conflict, conflict_detail "
                f"FROM web_battery_staging {where} "
                f"ORDER BY make_n, model_n, year "
                f"LIMIT :lim OFFSET :off"
            ),
            {"lim": page_size, "off": offset},
        ).fetchall()

    items = []
    for r in rows:
        d = dict(r._mapping)
        if isinstance(d.get("conflict_detail"), str):
            try:
                d["conflict_detail"] = json.loads(d["conflict_detail"])
            except Exception:
                pass
        items.append(d)

    return {"total": total, "items": items}


def patch_staging(row_id: int, ah: float, technology: str) -> None:
    VALID_TECH = {"MF", "AGM", "EFB", "GEL", "WET"}
    if not 20 <= ah <= 250:
        raise ValueError(f"Ah must be 20–250, got {ah}")
    if technology.upper() not in VALID_TECH:
        raise ValueError(f"Technology must be one of {VALID_TECH}")

    db = SessionLocal()
    try:
        db.execute(
            text(
                "UPDATE web_battery_staging SET ah = :ah, technology = :tech, "
                "is_valid = TRUE, invalid_reason = NULL WHERE id = :id"
            ),
            {"ah": ah, "tech": technology.upper(), "id": row_id},
        )
        db.commit()
    finally:
        db.close()


def pre_commit() -> dict:
    with engine.connect() as conn:
        staging = conn.execute(
            text("SELECT id, make_n, model_n, year, ah, technology FROM web_battery_staging WHERE is_valid = TRUE")
        ).fetchall()
        existing = conn.execute(
            text("SELECT make_n, model_n, year, ah, technology FROM web_battery_validation")
        ).fetchall()

    existing_map = {
        (r.make_n, r.model_n, r.year): {"ah": r.ah, "technology": r.technology}
        for r in existing
    }

    conflicts = []
    for r in staging:
        key = (r.make_n, r.model_n, r.year)
        if key in existing_map:
            cur = existing_map[key]
            ah_diff = abs((r.ah or 0) - (cur["ah"] or 0))
            tech_diff = (r.technology or "") != (cur["technology"] or "")
            if ah_diff > 5 or tech_diff:
                conflicts.append({
                    "id": r.id,
                    "make_n": r.make_n,
                    "model_n": r.model_n,
                    "year": r.year,
                    "staging_ah": r.ah,
                    "staging_tech": r.technology,
                    "current_ah": cur["ah"],
                    "current_tech": cur["technology"],
                })

    return {"conflict_count": len(conflicts), "conflicts": conflicts}


def commit_staging(resolutions: dict[int, str], committed_by: str) -> dict:
    """
    resolutions: {staging_row_id: "staging" | "current"}
    committed_by: admin username
    """
    db = SessionLocal()
    try:
        staging_rows = db.execute(
            text(
                "SELECT id, make_n, model_n, year, battery_code, ah, technology, source "
                "FROM web_battery_staging WHERE is_valid = TRUE"
            )
        ).fetchall()

        run_id_row = db.execute(
            text("SELECT run_id FROM web_battery_staging LIMIT 1")
        ).fetchone()
        run_id = run_id_row[0] if run_id_row else str(uuid.uuid4())

        existing_map: dict[tuple, dict] = {}
        existing_rows = db.execute(
            text("SELECT make_n, model_n, year, battery_code, ah, technology FROM web_battery_validation")
        ).fetchall()
        for r in existing_rows:
            existing_map[(r.make_n, r.model_n, r.year)] = dict(r._mapping)

        now = datetime.now(timezone.utc)
        added = updated = 0
        changelog_entries = []

        for r in staging_rows:
            key = (r.make_n, r.model_n, r.year)
            resolution = resolutions.get(r.id, "staging")
            if resolution == "current" and key in existing_map:
                continue  # keep existing, skip this staging row

            old = existing_map.get(key)
            new_vals = {
                "make_n": r.make_n, "model_n": r.model_n, "year": r.year,
                "battery_code": r.battery_code, "ah": r.ah,
                "technology": r.technology, "source": r.source,
            }

            if old:
                db.execute(
                    text(
                        "UPDATE web_battery_validation SET battery_code=:bc, ah=:ah, "
                        "technology=:tech, source=:src, validated_at=:ts "
                        "WHERE make_n=:mn AND model_n=:modn AND year=:yr"
                    ),
                    {**new_vals, "bc": r.battery_code, "ts": now,
                     "mn": r.make_n, "modn": r.model_n, "yr": r.year},
                )
                changelog_entries.append({
                    "change_type": "updated",
                    "make_n": r.make_n, "model_n": r.model_n, "year": r.year,
                    "old_values": json.dumps(old),
                    "new_values": json.dumps(new_vals),
                })
                updated += 1
            else:
                db.execute(
                    text(
                        "INSERT INTO web_battery_validation "
                        "(make_n, model_n, year, battery_code, ah, technology, source, validated_at) "
                        "VALUES (:mn, :modn, :yr, :bc, :ah, :tech, :src, :ts)"
                    ),
                    {"mn": r.make_n, "modn": r.model_n, "yr": r.year,
                     "bc": r.battery_code, "ah": r.ah, "tech": r.technology,
                     "src": r.source, "ts": now},
                )
                changelog_entries.append({
                    "change_type": "added",
                    "make_n": r.make_n, "model_n": r.model_n, "year": r.year,
                    "old_values": None,
                    "new_values": json.dumps(new_vals),
                })
                added += 1

        # Version record
        version_id = str(uuid.uuid4())
        prev = db.execute(
            text("SELECT MAX(version_number) FROM web_battery_validation_versions")
        ).scalar() or 0
        db.execute(
            text(
                "INSERT INTO web_battery_validation_versions "
                "(id, version_number, committed_at, run_id, committed_count, "
                "conflict_count, committed_by) "
                "VALUES (:vid, :vnum, :ts, :rid, :cnt, :cc, :by)"
            ),
            {
                "vid": version_id, "vnum": prev + 1, "ts": now,
                "rid": run_id, "cnt": added + updated,
                "cc": len([c for c in changelog_entries if c["change_type"] == "updated"]),
                "by": committed_by,
            },
        )

        # Changelog
        for entry in changelog_entries:
            db.execute(
                text(
                    "INSERT INTO web_battery_validation_changelog "
                    "(version_id, make_n, model_n, year, change_type, old_values, new_values) "
                    "VALUES (:vid, :mn, :modn, :yr, :ct, :ov, :nv)"
                ),
                {
                    "vid": version_id,
                    "mn": entry["make_n"], "modn": entry["model_n"], "yr": entry["year"],
                    "ct": entry["change_type"],
                    "ov": entry["old_values"],
                    "nv": entry["new_values"],
                },
            )

        db.execute(text("TRUNCATE web_battery_staging"))
        db.commit()
        return {"added": added, "updated": updated, "version": prev + 1}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def discard_staging() -> None:
    db = SessionLocal()
    try:
        db.execute(text("TRUNCATE web_battery_staging"))
        db.commit()
    finally:
        db.close()


# ── Versions ──────────────────────────────────────────────────────────────────

def get_versions(page: int = 1, page_size: int = 20) -> dict:
    offset = (page - 1) * page_size
    with engine.connect() as conn:
        total = conn.execute(
            text("SELECT COUNT(*) FROM web_battery_validation_versions")
        ).scalar() or 0
        rows = conn.execute(
            text(
                "SELECT id, version_number, committed_at, run_id, committed_count, "
                "conflict_count, notes, committed_by "
                "FROM web_battery_validation_versions "
                "ORDER BY version_number DESC LIMIT :lim OFFSET :off"
            ),
            {"lim": page_size, "off": offset},
        ).fetchall()
    return {"total": total, "items": [dict(r._mapping) for r in rows]}


def get_changelog(version_id: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT make_n, model_n, year, change_type, old_values, new_values "
                "FROM web_battery_validation_changelog WHERE version_id = :vid "
                "ORDER BY change_type, make_n, model_n, year"
            ),
            {"vid": version_id},
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r._mapping)
        for key in ("old_values", "new_values"):
            if isinstance(d.get(key), str):
                try:
                    d[key] = json.loads(d[key])
                except Exception:
                    pass
        result.append(d)
    return result


def revert_version(version_id: str, committed_by: str) -> int:
    db = SessionLocal()
    try:
        changelog = get_changelog(version_id)
        now = datetime.now(timezone.utc)

        for entry in changelog:
            ct = entry["change_type"]
            mn, modn, yr = entry["make_n"], entry["model_n"], entry["year"]
            old = entry.get("old_values") or {}
            new = entry.get("new_values") or {}

            if ct == "added":
                db.execute(
                    text("DELETE FROM web_battery_validation WHERE make_n=:mn AND model_n=:modn AND year=:yr"),
                    {"mn": mn, "modn": modn, "yr": yr},
                )
            elif ct == "removed":
                db.execute(
                    text(
                        "INSERT INTO web_battery_validation (make_n, model_n, year, battery_code, ah, technology, source, validated_at) "
                        "VALUES (:mn, :modn, :yr, :bc, :ah, :tech, :src, :ts) "
                        "ON CONFLICT (make_n, model_n, year) DO NOTHING"
                    ),
                    {"mn": mn, "modn": modn, "yr": yr, "bc": old.get("battery_code"), "ah": old.get("ah"),
                     "tech": old.get("technology"), "src": old.get("source"), "ts": now},
                )
            elif ct == "updated" and old:
                db.execute(
                    text(
                        "UPDATE web_battery_validation SET battery_code=:bc, ah=:ah, technology=:tech, "
                        "source=:src, validated_at=:ts WHERE make_n=:mn AND model_n=:modn AND year=:yr"
                    ),
                    {"bc": old.get("battery_code"), "ah": old.get("ah"), "tech": old.get("technology"),
                     "src": old.get("source"), "ts": now, "mn": mn, "modn": modn, "yr": yr},
                )

        # New version record for the revert
        prev = db.execute(
            text("SELECT MAX(version_number) FROM web_battery_validation_versions")
        ).scalar() or 0
        new_ver = prev + 1

        ver_row = db.execute(
            text("SELECT version_number FROM web_battery_validation_versions WHERE id = :vid"),
            {"vid": version_id},
        ).fetchone()
        ver_num = ver_row[0] if ver_row else "?"

        db.execute(
            text(
                "INSERT INTO web_battery_validation_versions "
                "(id, version_number, committed_at, committed_count, committed_by, notes) "
                "VALUES (:id, :vnum, :ts, :cnt, :by, :notes)"
            ),
            {
                "id": str(uuid.uuid4()), "vnum": new_ver, "ts": now,
                "cnt": len(changelog), "by": committed_by,
                "notes": f"Revert of version #{ver_num}",
            },
        )
        db.commit()
        return new_ver
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Matched / Unmatched ───────────────────────────────────────────────────────

def get_matched(page: int = 1, search: str = "", page_size: int = 50) -> dict:
    q = f"%{search.upper()}%" if search else "%"
    offset = (page - 1) * page_size
    with engine.connect() as conn:
        total = conn.execute(
            text(
                "SELECT COUNT(*) FROM web_battery_validation "
                "WHERE UPPER(make_n) LIKE :q OR UPPER(model_n) LIKE :q"
            ),
            {"q": q},
        ).scalar() or 0
        rows = conn.execute(
            text(
                "SELECT make_n, model_n, year, ah, technology, source, validated_at "
                "FROM web_battery_validation "
                "WHERE UPPER(make_n) LIKE :q OR UPPER(model_n) LIKE :q "
                "ORDER BY make_n, model_n, year LIMIT :lim OFFSET :off"
            ),
            {"q": q, "lim": page_size, "off": offset},
        ).fetchall()
    return {"total": total, "items": [dict(r._mapping) for r in rows]}


# ── API Quotas ────────────────────────────────────────────────────────────────

def get_quotas() -> list[dict]:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT provider, calls_made, quota_limit "
                "FROM api_usage_quota WHERE month = :month"
            ),
            {"month": month},
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r._mapping)
        limit = d.get("quota_limit", -1)
        made = d.get("calls_made", 0)
        d["pct_used"] = 0.0 if limit == -1 else round(made / limit * 100, 1) if limit else 0.0
        result.append(d)
    return result
