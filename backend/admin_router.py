"""
admin_router.py — All /api/admin/* routes.

Mount this in app.py:
    from admin_router import router as admin_router
    app.include_router(admin_router)

Endpoints
---------
POST   /api/admin/login
POST   /api/admin/logout
GET    /api/admin/me
GET    /api/admin/stats
GET    /api/admin/health
GET    /api/admin/batteries
POST   /api/admin/batteries
PATCH  /api/admin/batteries/{id}
DELETE /api/admin/batteries/{id}
POST   /api/admin/batteries/upload
GET    /api/admin/batteries/export
GET    /api/admin/audit
POST   /api/admin/cache/refresh
GET    /api/admin/sessions
DELETE /api/admin/sessions/{id}
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import requests
import matcher
import pandas as pd
from admin_auth import (
    COOKIE_NAME,
    clear_session_cookie,
    create_session,
    delete_session,
    require_admin,
    set_session_cookie,
    verify_password,
)
from db import SessionLocal, engine
from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from models import (
    AdminSession, AdminStats, AppSettings, AdminUser, BatteryAuditLog, BatterySpec,
    SearchEvent, UserFeedback, TestUser, TestUserSession,
    VehicleYear, VehicleYearStaging, VehicleYearVersion, VehicleYearChangelog,
    EnrichmentCacheMeta, FueleconomyVehicle, ExpansionMake,
)
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from upload_pipeline import process_battery_upload

import openpyxl

logger = logging.getLogger("battery_finder.admin")
router = APIRouter(prefix="/api/admin", tags=["admin"])
_limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# Web-validate pipeline in-memory state
# ---------------------------------------------------------------------------

_pipeline_lock = threading.Lock()
_pipeline_state: dict = {
    "run_id":           None,
    "status":           "idle",   # "idle" | "running" | "paused" | "done" | "error"
    "total":            0,
    "processed":        0,
    "found":            0,
    "not_found":        0,
    "current_provider": None,
    "current_combo":    None,
    "provider_counts":  {"duckduckgo": 0, "google_cse": 0, "tavily": 0},
    "logs":             deque(maxlen=50),
    "started_at":        None,
    "phase1_total":      0,
    "phase1_processed":  0,
    "phase2_started_at": None,
    "finished_at":       None,
    "error_detail":     None,
    "cancel_event":     None,
    "pause_event":      None,
    "initiated_by":     None,
}


# ---------------------------------------------------------------------------
# DB dependency
# ---------------------------------------------------------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


class BatteryCreateRequest(BaseModel):
    battery_code: str = Field(..., min_length=1, max_length=100)
    model_key:    str = Field(..., min_length=1, max_length=100)
    ah:           float = Field(..., gt=0)
    cca_en:       Optional[float] = Field(None, gt=0)
    technology:   str = Field(..., min_length=1, max_length=100)


class BatteryUpdateRequest(BaseModel):
    battery_code: str = Field(..., min_length=1, max_length=100)
    model_key:    str = Field(..., min_length=1, max_length=100)
    ah:           float = Field(..., gt=0)
    cca_en:       Optional[float] = Field(None, gt=0)
    technology:   str = Field(..., min_length=1, max_length=100)


# ---------------------------------------------------------------------------
# Auth endpoints (rate-limited — no auth required)
# ---------------------------------------------------------------------------

@router.post("/login")
@_limiter.limit("5/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter(AdminUser.username == body.username).first()
    # Always run verify_password to prevent timing attacks even on missing user
    dummy_hash = "$2b$12$notarealhashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
    hashed = user.password_hash if user else dummy_hash
    valid = verify_password(body.password, hashed)

    if not user or not valid:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    ip = request.client.host if request.client else None
    token = create_session(db, user, ip)

    response = JSONResponse(content={"username": user.username})
    set_session_cookie(response, token)
    logger.info("Admin login: %s from %s", user.username, ip)
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        delete_session(db, token)
    response = JSONResponse(content={"detail": "Logged out"})
    clear_session_cookie(response)
    return response


@router.get("/me")
def me(admin: AdminUser = Depends(require_admin)):
    return {"username": admin.username}


# ---------------------------------------------------------------------------
# Stats & health
# ---------------------------------------------------------------------------

@router.get("/stats")
def stats(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    # ── 1 query: all table counts via scalar subqueries ──────────────────────
    row = db.execute(text("""
        SELECT
            (SELECT COUNT(*)                                     FROM battery_specs      WHERE deleted_at IS NULL)  AS battery_specs,
            (SELECT COUNT(DISTINCT make || '|' || model)         FROM vehicle_years)                                AS vehicle_years,
            (SELECT COUNT(*)                                     FROM vehicles_raw)                                 AS vehicles_raw,
            (SELECT COUNT(*)                                     FROM model_aliases)                                AS model_aliases,
            (SELECT COUNT(DISTINCT vehicle_type)                 FROM dial_battery_inference)                       AS inf_makes,
            (SELECT COUNT(DISTINCT vehicle_model)                FROM dial_battery_inference)                       AS inf_models,
            (SELECT COUNT(*)                                     FROM dial_battery_inference)                       AS inf_records
    """)).fetchone()

    counts = {
        "battery_specs":    row.battery_specs    or 0,
        "vehicle_years":    row.vehicle_years    or 0,
        "vehicles_raw":     row.vehicles_raw     or 0,
        "model_aliases":    row.model_aliases    or 0,
        "inference_makes":  row.inf_makes        or 0,
        "inference_models": row.inf_models       or 0,
        "inference_records":row.inf_records      or 0,
    }

    # ── 1 query: db_reads ────────────────────────────────────────────────────
    reads_row = db.query(AdminStats).filter(AdminStats.stat_key == "db_reads").first()
    db_reads = reads_row.stat_value if reads_row else 0

    # ── 1 query: match breakdown via GROUP BY ─────────────────────────────────
    from datetime import timezone as _tz
    today_start = datetime.now(_tz.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    _MATCHED_TYPES  = ["Exact Match", "Web-Validated Match", "Real-World Data Match"]
    _CLOSE_TYPES    = ["Close Match"]
    _FALLBACK_TYPES = ["Estimated (Rule-Based)"]

    type_rows = (
        db.query(SearchEvent.match_type, func.count(SearchEvent.id))
        .filter(SearchEvent.timestamp >= today_start)
        .group_by(SearchEvent.match_type)
        .all()
    )
    counts_by_type = {match_type: n for match_type, n in type_rows}

    s_matched  = sum(counts_by_type.get(t, 0) for t in _MATCHED_TYPES)
    s_close    = sum(counts_by_type.get(t, 0) for t in _CLOSE_TYPES)
    s_fallback = sum(counts_by_type.get(t, 0) for t in _FALLBACK_TYPES)
    s_total    = s_matched + s_close + s_fallback

    return {
        "counts":    counts,
        "db_reads":  db_reads,
        "match_breakdown": {
            "matched":  s_matched,
            "close":    s_close,
            "fallback": s_fallback,
            "total":    s_total,
        },
    }


@router.get("/health")
def health(admin: AdminUser = Depends(require_admin)):
    # Connectivity + latency
    start = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        connected = True
    except Exception:
        latency_ms = None
        connected = False

    # Pool usage
    pool = engine.pool
    pool_size   = pool.size()
    checked_out = pool.checkedout()
    overflow    = pool.overflow()
    total_conns = pool_size + max(overflow, 0)
    pool_pct    = round((checked_out / max(total_conns, 1)) * 100, 1)

    if not connected:
        status = "down"
    elif latency_ms is not None and latency_ms > 500:
        status = "degraded"
    elif pool_pct > 85:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status":        status,
        "connected":     connected,
        "latency_ms":    latency_ms,
        "pool_size":     pool_size,
        "pool_checked_out": checked_out,
        "pool_usage_pct":   pool_pct,
    }


# ---------------------------------------------------------------------------
# Battery CRUD
# ---------------------------------------------------------------------------

@router.get("/batteries")
def list_batteries(
    page:       int = 1,
    page_size:  int = 50,
    search:     Optional[str] = None,
    technology: Optional[str] = None,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(BatterySpec).filter(BatterySpec.deleted_at.is_(None))
    if search:
        like = f"%{search.upper()}%"
        query = query.filter(
            BatterySpec.battery_code.ilike(like) | BatterySpec.model_key.ilike(like)
        )
    if technology:
        query = query.filter(BatterySpec.technology.ilike(f"%{technology}%"))

    total = query.count()
    items = query.order_by(BatterySpec.battery_code).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page":  page,
        "page_size": page_size,
        "items": [
            {
                "id":           b.id,
                "battery_code": b.battery_code,
                "model_key":    b.model_key,
                "ah":           b.ah,
                "cca_en":       b.cca_en,
                "technology":   b.technology,
                "origin":       b.origin,
                "brand":        b.brand,
            }
            for b in items
        ],
    }


@router.post("/batteries", status_code=201)
def add_battery(
    body: BatteryCreateRequest,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    existing = db.query(BatterySpec).filter(
        BatterySpec.battery_code == body.battery_code.upper()
    ).first()
    if existing and existing.deleted_at is None:
        raise HTTPException(status_code=409, detail=f"battery_code {body.battery_code!r} already exists")

    new_b = BatterySpec(
        battery_code=body.battery_code.upper(),
        model_key=body.model_key.upper(),
        ah=body.ah,
        cca_en=body.cca_en,
        technology=body.technology.upper(),
    )
    db.add(new_b)
    db.flush()

    log = BatteryAuditLog(
        battery_id=new_b.id,
        action="INSERT",
        changed_by=admin.username,
        changed_at=datetime.now(timezone.utc),
        old_values=None,
        new_values=json.dumps({
            "battery_code": new_b.battery_code,
            "model_key":    new_b.model_key,
            "ah":           new_b.ah,
            "cca_en":       new_b.cca_en,
            "technology":   new_b.technology,
        }),
    )
    db.add(log)
    db.commit()

    # Invalidate matcher cache so new battery is visible immediately
    matcher._batteries.cache_clear()
    matcher.recommend.cache_clear()

    return {"id": new_b.id, "battery_code": new_b.battery_code}


@router.patch("/batteries/{battery_id}")
def update_battery(
    battery_id: int,
    body: BatteryUpdateRequest,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    battery = db.query(BatterySpec).filter(
        BatterySpec.id == battery_id,
        BatterySpec.deleted_at.is_(None),
    ).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery not found")

    # Check new battery_code doesn't clash with another row
    code_upper = body.battery_code.upper()
    clash = db.query(BatterySpec).filter(
        BatterySpec.battery_code == code_upper,
        BatterySpec.id != battery_id,
        BatterySpec.deleted_at.is_(None),
    ).first()
    if clash:
        raise HTTPException(status_code=409, detail=f"battery_code {code_upper!r} already used by another battery")

    old = {
        "battery_code": battery.battery_code,
        "model_key":    battery.model_key,
        "ah":           battery.ah,
        "cca_en":       battery.cca_en,
        "technology":   battery.technology,
    }

    battery.battery_code = code_upper
    battery.model_key    = body.model_key.upper()
    battery.ah           = body.ah
    battery.cca_en       = body.cca_en
    battery.technology   = body.technology.upper()

    new = {
        "battery_code": battery.battery_code,
        "model_key":    battery.model_key,
        "ah":           battery.ah,
        "cca_en":       battery.cca_en,
        "technology":   battery.technology,
    }

    log = BatteryAuditLog(
        battery_id=battery.id,
        action="UPDATE",
        changed_by=admin.username,
        changed_at=datetime.now(timezone.utc),
        old_values=json.dumps(old),
        new_values=json.dumps(new),
    )
    db.add(log)
    db.commit()

    matcher._batteries.cache_clear()
    matcher.recommend.cache_clear()
    return {"detail": "updated", "battery_code": battery.battery_code}


@router.delete("/batteries/{battery_id}")
def delete_battery(
    battery_id: int,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    battery = db.query(BatterySpec).filter(
        BatterySpec.id == battery_id,
        BatterySpec.deleted_at.is_(None),
    ).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery not found")

    old = {
        "battery_code": battery.battery_code,
        "model_key":    battery.model_key,
        "ah":           battery.ah,
        "cca_en":       battery.cca_en,
        "technology":   battery.technology,
    }

    battery.deleted_at = datetime.now(timezone.utc)

    log = BatteryAuditLog(
        battery_id=battery.id,
        action="DELETE",
        changed_by=admin.username,
        changed_at=datetime.now(timezone.utc),
        old_values=json.dumps(old),
        new_values=None,
    )
    db.add(log)
    db.commit()

    matcher._batteries.cache_clear()
    matcher.recommend.cache_clear()
    return {"detail": "deleted", "battery_code": battery.battery_code}


# ---------------------------------------------------------------------------
# Excel upload
# ---------------------------------------------------------------------------

@router.post("/batteries/upload")
async def upload_batteries(
    file: UploadFile = File(...),
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are accepted")

    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:  # 10 MB guard
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    try:
        result = process_battery_upload(raw, db, changed_by=admin.username)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    matcher._batteries.cache_clear()
    matcher.recommend.cache_clear()

    return {
        "inserted":          result.inserted,
        "updated":           result.updated,
        "skipped_unchanged": result.skipped_unchanged,
        "rejected":          result.rejected,
        "errors": [
            {"row": e.row, "battery_code": e.battery_code, "reason": e.reason}
            for e in result.errors
        ],
    }


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------

@router.get("/batteries/export")
def export_batteries(
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    batteries = (
        db.query(BatterySpec)
        .filter(BatterySpec.deleted_at.is_(None))
        .order_by(BatterySpec.battery_code)
        .all()
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "battery_specs"
    ws.append(["battery_code", "model_key", "ah", "cca_en", "technology"])
    for b in batteries:
        ws.append([b.battery_code, b.model_key, b.ah, b.cca_en, b.technology])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"battery_specs_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@router.get("/audit/users")
def audit_users(
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = (
        db.query(BatteryAuditLog.changed_by)
        .distinct()
        .order_by(BatteryAuditLog.changed_by)
        .all()
    )
    return {"users": [u[0] for u in users]}


@router.get("/audit")
def audit_log(
    page:         int = 1,
    page_size:    int = 50,
    action:       Optional[str] = None,   # comma-separated: INSERT,UPDATE,DELETE
    changed_by:   Optional[str] = None,   # partial match on admin username
    battery_code: Optional[str] = None,   # search inside JSON values
    date_from:    Optional[str] = None,   # YYYY-MM-DD
    date_to:      Optional[str] = None,   # YYYY-MM-DD
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(BatteryAuditLog).order_by(BatteryAuditLog.changed_at.desc())

    if action:
        actions = [a.strip().upper() for a in action.split(',') if a.strip()]
        if actions:
            query = query.filter(BatteryAuditLog.action.in_(actions))

    if changed_by:
        query = query.filter(BatteryAuditLog.changed_by.ilike(f"%{changed_by}%"))

    if battery_code:
        bc = battery_code.upper()
        from sqlalchemy import or_
        query = query.filter(
            or_(
                BatteryAuditLog.old_values.ilike(f"%{bc}%"),
                BatteryAuditLog.new_values.ilike(f"%{bc}%"),
            )
        )

    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
            query = query.filter(BatteryAuditLog.changed_at >= dt_from)
        except ValueError:
            pass

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to + "T23:59:59").replace(tzinfo=timezone.utc)
            query = query.filter(BatteryAuditLog.changed_at <= dt_to)
        except ValueError:
            pass

    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page":  page,
        "items": [
            {
                "id":          e.id,
                "battery_id":  e.battery_id,
                "action":      e.action,
                "changed_by":  e.changed_by,
                "changed_at":  e.changed_at.isoformat(),
                "old_values":  json.loads(e.old_values) if e.old_values else None,
                "new_values":  json.loads(e.new_values) if e.new_values else None,
            }
            for e in items
        ],
    }


# ---------------------------------------------------------------------------
# Cache refresh
# ---------------------------------------------------------------------------

@router.post("/cache/refresh")
def refresh_cache(admin: AdminUser = Depends(require_admin)):
    matcher._vehicles.cache_clear()
    matcher._batteries.cache_clear()
    matcher._model_aliases.cache_clear()
    matcher._inference.cache_clear()
    matcher.recommend.cache_clear()
    # Re-warm immediately
    matcher._vehicles()
    matcher._batteries()
    matcher._model_aliases()
    matcher._inference()
    logger.info("Matcher cache refreshed by %s", admin.username)
    return {"detail": "Cache refreshed"}


# ---------------------------------------------------------------------------
# Maintenance mode
# ---------------------------------------------------------------------------

class MaintenanceModeRequest(BaseModel):
    enabled: bool


@router.get("/maintenance")
def get_maintenance_mode(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    from app_state import is_maintenance_mode
    return {"enabled": is_maintenance_mode()}


@router.post("/maintenance")
def set_maintenance_mode_route(
    body: MaintenanceModeRequest,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app_state import set_maintenance_mode
    row = db.query(AppSettings).filter_by(setting_key="maintenance_mode").first()
    now = datetime.now(timezone.utc)
    if row:
        row.setting_value = "true" if body.enabled else "false"
        row.updated_at    = now
        row.updated_by    = admin.username
    else:
        db.add(AppSettings(
            setting_key="maintenance_mode",
            setting_value="true" if body.enabled else "false",
            updated_at=now,
            updated_by=admin.username,
        ))
    db.commit()
    set_maintenance_mode(body.enabled)
    logger.info("Maintenance mode set to %s by %s", body.enabled, admin.username)
    return {"enabled": body.enabled}


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

@router.get("/sessions")
def list_sessions(
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    sessions = (
        db.query(AdminSession)
        .filter(AdminSession.admin_id == admin.id)
        .order_by(AdminSession.created_at.desc())
        .all()
    )
    now = datetime.now(timezone.utc)
    return {
        "sessions": [
            {
                "id":         s.id,
                "created_at": s.created_at.isoformat(),
                "expires_at": s.expires_at.isoformat(),
                "ip_address": s.ip_address,
                "expired":    now >= s.expires_at,
            }
            for s in sessions
        ]
    }


@router.delete("/sessions/{session_id}")
def revoke_session(
    session_id: int,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    session = db.query(AdminSession).filter(
        AdminSession.id == session_id,
        AdminSession.admin_id == admin.id,   # can only revoke own sessions
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(session)
    db.commit()
    return {"detail": "Session revoked"}


# ---------------------------------------------------------------------------
# Search events log
# ---------------------------------------------------------------------------

@router.get("/search-events", summary="Paginated search events log")
def list_search_events(
    page: int = 1,
    page_size: int = 50,
    match_type: Optional[str] = None,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    page_size = min(max(page_size, 1), 100)
    q = db.query(SearchEvent)
    if match_type:
        q = q.filter(SearchEvent.match_type == match_type)
    total = q.count()
    rows = q.order_by(SearchEvent.timestamp.desc()).offset((page - 1) * page_size).limit(page_size).all()
    items = [
        {
            "id":               r.id,
            "timestamp":        r.timestamp.isoformat(),
            "make":             r.make,
            "model":            r.model,
            "year":             r.year,
            "engine_cc":        r.engine_cc,
            "fuel_type":        r.fuel_type,
            "battery_returned": r.battery_returned,
            "battery_ah":       r.battery_ah,
            "match_type":       r.match_type,
            "confidence":       r.confidence,
            "matched":          r.matched,
            "ip_address":       r.ip_address,
        }
        for r in rows
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# Feedback report
# ---------------------------------------------------------------------------

@router.get("/feedback", summary="Paginated user feedback report")
def list_feedback(
    page: int = 1,
    page_size: int = 25,
    accuracy: Optional[str] = None,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    import json as _json
    page_size = min(max(page_size, 1), 100)
    q = db.query(UserFeedback)
    if accuracy:
        q = q.filter(UserFeedback.accuracy == accuracy)
    total = q.count()
    rows = (
        q.outerjoin(TestUser, UserFeedback.test_user_id == TestUser.id)
        .add_columns(TestUser.username)
        .order_by(UserFeedback.submitted_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "id":              r.UserFeedback.id,
            "vehicle_label":   r.UserFeedback.vehicle_label,
            "satisfaction":    r.UserFeedback.satisfaction,
            "accuracy":        r.UserFeedback.accuracy,
            "wrong_parts":     _json.loads(r.UserFeedback.wrong_parts) if r.UserFeedback.wrong_parts else None,
            "comments":        r.UserFeedback.comments,
            "submitted_at":    r.UserFeedback.submitted_at.isoformat(),
            "ip_address":      r.UserFeedback.ip_address,
            "test_username":   r.username,
            "input_type":      r.UserFeedback.input_type,
            "match_confidence": r.UserFeedback.match_confidence,
            "match_type":      r.UserFeedback.match_type,
            "recommended_battery": r.UserFeedback.recommended_battery,
        }
        for r in rows
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/feedback/summary", summary="Aggregate feedback statistics")
def feedback_summary(
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total = db.query(func.count(UserFeedback.id)).scalar() or 0
    avg_satisfaction = db.query(func.avg(UserFeedback.satisfaction)).scalar()
    accuracy_counts = (
        db.query(UserFeedback.accuracy, func.count(UserFeedback.id))
        .group_by(UserFeedback.accuracy)
        .all()
    )
    star_counts = (
        db.query(UserFeedback.satisfaction, func.count(UserFeedback.id))
        .group_by(UserFeedback.satisfaction)
        .order_by(UserFeedback.satisfaction)
        .all()
    )
    return {
        "total": total,
        "avg_satisfaction": round(float(avg_satisfaction), 2) if avg_satisfaction else None,
        "accuracy_breakdown": {k or "not_given": v for k, v in accuracy_counts},
        "star_breakdown": {str(s): c for s, c in star_counts},
    }


@router.get("/feedback/export-pdf", summary="Export full feedback report as PDF")
def export_feedback_pdf(
    accuracy: Optional[str] = None,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    import io
    import json as _json
    from datetime import date
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph,
        Spacer, HRFlowable,
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER

    # ── Fetch all rows (no pagination for export) ──────────────────────────
    q = db.query(UserFeedback)
    if accuracy:
        q = q.filter(UserFeedback.accuracy == accuracy)
    rows = q.order_by(UserFeedback.submitted_at.desc()).all()

    # ── Summary stats ──────────────────────────────────────────────────────
    total = len(rows)
    avg_sat = (sum(r.satisfaction for r in rows) / total) if total else None
    accuracy_counts: dict[str, int] = {}
    for r in rows:
        key = r.accuracy or "not_given"
        accuracy_counts[key] = accuracy_counts.get(key, 0) + 1
    star_counts: dict[int, int] = {}
    for r in rows:
        star_counts[r.satisfaction] = star_counts.get(r.satisfaction, 0) + 1

    # ── Build PDF in memory ─────────────────────────────────────────────────
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm,  bottomMargin=1.5*cm,
    )

    styles     = getSampleStyleSheet()
    RED        = colors.HexColor("#CC0000")
    LIGHT_GREY = colors.HexColor("#f3f4f6")
    MID_GREY   = colors.HexColor("#6b7280")

    title_style = ParagraphStyle(
        "Title", parent=styles["Heading1"],
        textColor=RED, fontSize=18, spaceAfter=4, fontName="Helvetica-Bold",
    )
    sub_style = ParagraphStyle(
        "Sub", parent=styles["Normal"],
        textColor=MID_GREY, fontSize=9, spaceAfter=10,
    )
    cell_style = ParagraphStyle(
        "Cell", parent=styles["Normal"],
        fontSize=7.5, leading=10, wordWrap="CJK",
    )

    def stars(n: int) -> str:
        return "★" * n + "☆" * (5 - n)

    accuracy_label = {
        "exact": "Exact match", "close": "Close", "wrong": "Wrong",
        "unsure": "Unsure", "not_given": "Not given",
    }

    story = []

    # Title
    filter_note = f" — filtered: {accuracy}" if accuracy else ""
    story.append(Paragraph(f"Battery Finder — Feedback Report{filter_note}", title_style))
    story.append(Paragraph(
        f"Generated {date.today().strftime('%B %d, %Y')} by {admin.username}  ·  {total} response{'s' if total != 1 else ''}",
        sub_style,
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=RED, spaceAfter=10))

    # Summary table
    acc_str = "  |  ".join(
        f"{accuracy_label.get(k, k)}: {v}" for k, v in sorted(accuracy_counts.items())
    ) or "—"
    star_str = "  ".join(f"{s}★:{c}" for s, c in sorted(star_counts.items(), reverse=True))
    summary_data = [
        ["Total responses", "Avg satisfaction", "Star breakdown", "Accuracy breakdown"],
        [
            str(total),
            f"{avg_sat:.1f} / 5.0" if avg_sat else "—",
            star_str or "—",
            acc_str,
        ],
    ]
    summary_table = Table(summary_data, colWidths=[3.5*cm, 3.5*cm, 8*cm, None])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), RED),
        ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, 0), 8),
        ("FONTSIZE",    (0, 1), (-1, 1), 9),
        ("FONTNAME",    (0, 1), (-1, 1), "Helvetica-Bold"),
        ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, 1), [LIGHT_GREY]),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e4e9")),
        ("TOPPADDING",  (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.4*cm))

    # Main data table
    col_headers = ["#", "Vehicle", "Battery Returned", "Accuracy", "Wrong parts flagged", "Comments", "Submitted at"]
    table_data = [col_headers]
    for idx, r in enumerate(rows, 1):
        wrong = ""
        if r.wrong_parts:
            try:
                wp = _json.loads(r.wrong_parts)
                flagged = [k.replace("_", " ").title() for k, v in wp.items() if v]
                wrong = ", ".join(flagged)
            except Exception:
                wrong = ""
        table_data.append([
            str(idx),
            Paragraph(r.vehicle_label or "", cell_style),
            Paragraph(r.recommended_battery or "—", cell_style),
            accuracy_label.get(r.accuracy or "", r.accuracy or "—"),
            Paragraph(wrong or "—", cell_style),
            Paragraph((r.comments or "—")[:300], cell_style),
            r.submitted_at.strftime("%Y-%m-%d %H:%M") if r.submitted_at else "—",
        ])

    page_w = landscape(A4)[0] - 3*cm   # total usable width
    col_widths = [0.7*cm, 4.5*cm, 3*cm, 2.2*cm, 4*cm, None, 3.2*cm]
    # let "comments" fill remaining space
    fixed = sum(w for w in col_widths if w is not None)
    col_widths[5] = page_w - fixed

    main_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    main_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), RED),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 8),
        ("FONTSIZE",      (0, 1), (-1, -1), 7.5),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("ALIGN",         (0, 0), (0, -1), "CENTER"),   # # col
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e4e9")),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(main_table)

    doc.build(story)
    buf.seek(0)
    filename = f"feedback_report_{date.today().isoformat()}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/feedback/export-csv", summary="Export full feedback report as CSV")
def export_feedback_csv(
    accuracy: Optional[str] = None,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    import csv
    import io
    import json as _json
    from datetime import date

    q = db.query(UserFeedback)
    if accuracy:
        q = q.filter(UserFeedback.accuracy == accuracy)
    rows = (
        q.outerjoin(TestUser, UserFeedback.test_user_id == TestUser.id)
        .add_columns(TestUser.username)
        .order_by(UserFeedback.submitted_at.desc())
        .all()
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "ID", "User", "Vehicle", "Battery Returned", "Accuracy", "Input Type",
        "Match Confidence", "Match Type", "Wrong Parts Flagged", "Comments",
        "IP Address", "Submitted At",
    ])
    for r in rows:
        wrong = ""
        if r.UserFeedback.wrong_parts:
            try:
                wp = _json.loads(r.UserFeedback.wrong_parts)
                flagged = [k.replace("_", " ").title() for k, v in wp.items() if v]
                wrong = ", ".join(flagged)
            except Exception:
                wrong = ""
        writer.writerow([
            r.UserFeedback.id,
            r.username or "anonymous",
            r.UserFeedback.vehicle_label or "",
            r.UserFeedback.recommended_battery or "",
            r.UserFeedback.accuracy or "",
            r.UserFeedback.input_type or "",
            r.UserFeedback.match_confidence if r.UserFeedback.match_confidence is not None else "",
            r.UserFeedback.match_type or "",
            wrong,
            r.UserFeedback.comments or "",
            r.UserFeedback.ip_address or "",
            r.UserFeedback.submitted_at.strftime("%Y-%m-%d %H:%M:%S") if r.UserFeedback.submitted_at else "",
        ])

    buf.seek(0)
    filename = f"feedback_report_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Test-user session management (admin view)
# ---------------------------------------------------------------------------

@router.get("/test-sessions", summary="List all test-user sessions")
def list_test_sessions(
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    rows = (
        db.query(TestUserSession, TestUser.username)
        .join(TestUser, TestUser.id == TestUserSession.user_id)
        .order_by(TestUserSession.created_at.desc())
        .all()
    )
    return {
        "sessions": [
            {
                "id":           s.id,
                "username":     username,
                "user_id":      s.user_id,
                "created_at":   s.created_at.isoformat(),
                "expires_at":   s.expires_at.isoformat(),
                "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
                "ip_address":   s.ip_address,
                "user_agent":   s.user_agent,
                "expired":      now >= s.expires_at,
            }
            for s, username in rows
        ]
    }


@router.delete("/test-sessions/{session_id}", summary="Revoke a test-user session")
def revoke_test_session(
    session_id: int,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    session = db.query(TestUserSession).filter(TestUserSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(session)
    db.commit()
    return {"detail": "Session revoked"}


@router.get("/test-users", summary="List all test users")
def list_test_users(
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    session_counts_sq = (
        db.query(
            TestUserSession.user_id,
            func.count(TestUserSession.id).label("active_sessions"),
        )
        .filter(TestUserSession.expires_at > now)
        .group_by(TestUserSession.user_id)
        .subquery()
    )
    rows = (
        db.query(TestUser, func.coalesce(session_counts_sq.c.active_sessions, 0).label("active_sessions"))
        .outerjoin(session_counts_sq, session_counts_sq.c.user_id == TestUser.id)
        .order_by(TestUser.created_at.desc())
        .all()
    )
    return {
        "users": [
            {
                "id":              u.id,
                "username":        u.username,
                "email":           u.email,
                "created_at":      u.created_at.isoformat(),
                "is_active":       bool(u.is_active),
                "active_sessions": int(count),
            }
            for u, count in rows
        ]
    }


# ---------------------------------------------------------------------------
# Web-validate pipeline endpoints
# ---------------------------------------------------------------------------

class RunWebValidateBody(BaseModel):
    enabled_providers: list[str] | None = None  # None = use all available providers
    phase: str = "phase1"                       # "phase1", "phase2", or "both"


def _web_validate_thread(
    run_id: str,
    cancel_event: threading.Event,
    pause_event: threading.Event,
    enabled_providers: list[str] | None = None,
    phase: str = "phase1",
) -> None:
    """Background thread that runs the web_battery_validate pipeline."""
    from pipelines.web_battery_validate import main as _run_web_validate

    def _progress(processed: int, total: int, provider: str, combo_label: str = "") -> None:
        with _pipeline_lock:
            _pipeline_state["processed"] = processed
            if total > 0:
                _pipeline_state["total"] = total
            _pipeline_state["current_provider"] = provider
            if combo_label:
                _pipeline_state["current_combo"] = combo_label
            if provider in _pipeline_state["provider_counts"]:
                _pipeline_state["provider_counts"][provider] += 1
            if _pipeline_state["phase2_started_at"] is None and processed > 0:
                _pipeline_state["phase2_started_at"] = datetime.now(timezone.utc).isoformat()

    def _log_cb(line: str) -> None:
        with _pipeline_lock:
            _pipeline_state["logs"].append(line)

    def _phase1_progress(fetched: int, total: int) -> None:
        with _pipeline_lock:
            _pipeline_state["phase1_processed"] = fetched
            _pipeline_state["phase1_total"]     = total

    try:
        result = _run_web_validate(cancel_event, pause_event, _progress, _log_cb, enabled_providers, run_id,
                                   phase1_progress_callback=_phase1_progress,
                                   phase=phase)
        # Populate staging when Phase 2 completes normally (not on cancel)
        if not cancel_event.is_set() and phase in ("phase2", "both"):
            try:
                _populate_staging(run_id)
            except Exception as exc:
                logger.warning("Failed to populate staging after Phase 2 completion: %s", exc)
        with _pipeline_lock:
            _pipeline_state["status"]          = "cancelled" if cancel_event.is_set() else "done"
            _pipeline_state["found"]           = result["fetched"]
            _pipeline_state["not_found"]       = result["failed"]
            _pipeline_state["provider_counts"] = result["provider_counts"]
            _pipeline_state["finished_at"]     = datetime.now(timezone.utc).isoformat()
            _pipeline_state["error_detail"]    = None
    except Exception as exc:
        with _pipeline_lock:
            _pipeline_state["status"]       = "error"
            _pipeline_state["finished_at"]  = datetime.now(timezone.utc).isoformat()
            _pipeline_state["error_detail"] = str(exc)
        logger.exception("web_battery_validate pipeline error: %s", exc)


@router.post("/pipeline/web-validate/run", summary="Launch the web battery validation pipeline")
def run_web_validate(
    body: RunWebValidateBody = Body(default_factory=RunWebValidateBody),
    admin: AdminUser = Depends(require_admin),
):
    with _pipeline_lock:
        if _pipeline_state["status"] == "running":
            raise HTTPException(status_code=409, detail="Pipeline is already running")

        run_id = str(uuid.uuid4())
        cancel_ev = threading.Event()
        pause_ev  = threading.Event()
        _pipeline_state.update({
            "run_id":             run_id,
            "status":             "running",
            "total":              0,
            "processed":          0,
            "found":              0,
            "not_found":          0,
            "current_provider":   None,
            "current_combo":      None,
            "enabled_providers":  body.enabled_providers,
            "provider_counts":    {"duckduckgo": 0, "google_cse": 0, "tavily": 0},
            "logs":               deque(maxlen=50),
            "started_at":         datetime.now(timezone.utc).isoformat(),
            "phase1_total":       0,
            "phase1_processed":   0,
            "phase2_started_at":  None,
            "finished_at":        None,
            "error_detail":       None,
            "cancel_event":       cancel_ev,
            "pause_event":        pause_ev,
            "initiated_by":       admin.username,
        })

    t = threading.Thread(
        target=_web_validate_thread,
        args=(run_id, cancel_ev, pause_ev, body.enabled_providers, body.phase),
        daemon=True,
        name=f"web-validate-{run_id[:8]}",
    )
    t.start()
    logger.info(
        "web_battery_validate started by %s, run_id=%s, providers=%s",
        admin.username, run_id, body.enabled_providers,
    )
    return {"run_id": run_id}


@router.get("/pipeline/web-validate/status", summary="Get web-validate pipeline status")
def get_web_validate_status(admin: AdminUser = Depends(require_admin)):
    with _pipeline_lock:
        state = dict(_pipeline_state)
        state["logs"] = list(state["logs"])   # deque → list for JSON
        state.pop("cancel_event", None)        # threading.Event — not serialisable
        state.pop("pause_event", None)         # threading.Event — not serialisable
    return state


@router.post("/pipeline/web-validate/pause", summary="Pause the running web-validate pipeline")
def pause_web_validate(admin: AdminUser = Depends(require_admin)):
    with _pipeline_lock:
        if _pipeline_state["status"] != "running":
            raise HTTPException(status_code=400, detail="Pipeline is not currently running")
        pause_ev = _pipeline_state.get("pause_event")
        _pipeline_state["status"] = "paused"
    if pause_ev:
        pause_ev.set()
    logger.info("web_battery_validate pause requested by %s", admin.username)
    return {"detail": "Pause signal sent"}


@router.post("/pipeline/web-validate/resume", summary="Resume a paused web-validate pipeline")
def resume_web_validate(admin: AdminUser = Depends(require_admin)):
    with _pipeline_lock:
        if _pipeline_state["status"] != "paused":
            raise HTTPException(status_code=400, detail="Pipeline is not currently paused")
        pause_ev = _pipeline_state.get("pause_event")
        _pipeline_state["status"] = "running"
    if pause_ev:
        pause_ev.clear()
    logger.info("web_battery_validate resume requested by %s", admin.username)
    return {"detail": "Resume signal sent"}


@router.post("/pipeline/web-validate/cancel", summary="Cancel the running web-validate pipeline")
def cancel_web_validate(admin: AdminUser = Depends(require_admin)):
    with _pipeline_lock:
        if _pipeline_state["status"] not in ("running", "paused"):
            raise HTTPException(status_code=400, detail="Pipeline is not running or paused")
        cancel_ev  = _pipeline_state.get("cancel_event")
        pause_ev   = _pipeline_state.get("pause_event")
        run_id     = _pipeline_state.get("run_id")
        started_at = _pipeline_state.get("started_at")

    # Unblock pause loop first so the thread can see the cancel signal
    if pause_ev:
        pause_ev.clear()
    if cancel_ev:
        cancel_ev.set()

    # Wait up to 3 s for the thread to exit so DB rows are fully flushed
    deadline = time.time() + 3.0
    while time.time() < deadline:
        with _pipeline_lock:
            if _pipeline_state["status"] not in ("running", "paused"):
                break
        time.sleep(0.1)

    # Populate staging area from this run's records
    staged_count = invalid_count = conflict_count = 0
    if run_id:
        try:
            staged_count, invalid_count, conflict_count = _populate_staging(run_id)
        except Exception as exc:
            logger.warning("Failed to populate staging after cancel: %s", exc)

    logger.info(
        "web_battery_validate cancelled by %s — staged=%d invalid=%d conflicts=%d",
        admin.username, staged_count, invalid_count, conflict_count,
    )
    return {
        "detail":         "Pipeline cancelled",
        "staged_count":   staged_count,
        "invalid_count":  invalid_count,
        "conflict_count": conflict_count,
    }


# ---------------------------------------------------------------------------
# Staging area helpers
# ---------------------------------------------------------------------------

_VALID_TECHNOLOGIES = {"MF", "AGM", "EFB", "GEL", "WET"}


def _validate_staging_row(ah, technology, battery_code) -> tuple[bool, str | None]:
    """Return (is_valid, invalid_reason)."""
    if battery_code is None:
        return False, "No battery code resolved"
    if ah is not None and (ah < 20 or ah > 250):
        return False, f"Ah value out of range (20–250), got {ah}"
    if technology is not None and technology.upper() not in _VALID_TECHNOLOGIES:
        return False, f"Unknown technology type: {technology}"
    return True, None


def _populate_staging(run_id: str) -> tuple[int, int, int]:
    """
    Copy records from web_battery_validation (for this run_id) into
    web_battery_staging with validation + conflict flags applied.

    Returns (staged_count, invalid_count, conflict_count).
    """
    staged = invalid = conflicts = 0
    with engine.begin() as conn:
        # Fetch this run's rows from master
        rows = conn.execute(
            text(
                "SELECT make_n, model_n, year, battery_code, ah, technology,"
                " source, engine_cc, fuel_type"
                " FROM web_battery_validation WHERE run_id = :rid"
            ),
            {"rid": run_id},
        ).fetchall()

        if not rows:
            return 0, 0, 0

        # Clear any previous staging data (only one staging set at a time)
        conn.execute(text("TRUNCATE web_battery_staging"))

        for r in rows:
            make_n, model_n, year = r.make_n, r.model_n, r.year
            ah, technology, battery_code = r.ah, r.technology, r.battery_code

            is_valid, invalid_reason = _validate_staging_row(ah, technology, battery_code)

            # Check for conflict: master has a row for same key with a DIFFERENT run_id
            conflict = False
            conflict_detail = None
            existing = conn.execute(
                text(
                    "SELECT battery_code, ah, technology, source, run_id"
                    " FROM web_battery_validation"
                    " WHERE make_n=:mn AND model_n=:mo AND year=:yr"
                    "   AND run_id IS DISTINCT FROM :rid"
                ),
                {"mn": make_n, "mo": model_n, "yr": year, "rid": run_id},
            ).fetchone()
            if existing:
                # Conflict if ah or technology differ meaningfully
                ah_diff = abs((existing.ah or 0) - (ah or 0)) > 5 if (existing.ah and ah) else False
                tech_diff = (existing.technology or "").upper() != (technology or "").upper()
                if ah_diff or tech_diff:
                    conflict = True
                    conflicts += 1
                    conflict_detail = json.dumps({
                        "current": {
                            "ah": existing.ah, "technology": existing.technology,
                            "source": existing.source, "run_id": existing.run_id,
                        },
                        "staged": {"ah": ah, "technology": technology, "source": r.source},
                    })

            conn.execute(
                text(
                    "INSERT INTO web_battery_staging"
                    " (run_id, make_n, model_n, year, battery_code, ah, technology,"
                    "  source, engine_cc, fuel_type, is_valid, invalid_reason, conflict, conflict_detail)"
                    " VALUES"
                    " (:rid, :mn, :mo, :yr, :bc, :ah, :tech,"
                    "  :src, :ecc, :ft, :iv, :ir, :cf, :cd)"
                    " ON CONFLICT (make_n, model_n, year) DO UPDATE SET"
                    "  run_id=EXCLUDED.run_id, battery_code=EXCLUDED.battery_code,"
                    "  ah=EXCLUDED.ah, technology=EXCLUDED.technology,"
                    "  source=EXCLUDED.source, engine_cc=EXCLUDED.engine_cc,"
                    "  fuel_type=EXCLUDED.fuel_type, is_valid=EXCLUDED.is_valid,"
                    "  invalid_reason=EXCLUDED.invalid_reason, conflict=EXCLUDED.conflict,"
                    "  conflict_detail=EXCLUDED.conflict_detail, staged_at=now()"
                ),
                {
                    "rid": run_id, "mn": make_n, "mo": model_n, "yr": year,
                    "bc": battery_code, "ah": ah, "tech": technology,
                    "src": r.source, "ecc": r.engine_cc, "ft": r.fuel_type,
                    "iv": is_valid, "ir": invalid_reason,
                    "cf": conflict, "cd": conflict_detail,
                },
            )
            staged += 1
            if not is_valid:
                invalid += 1

    return staged, invalid, conflicts


@router.get("/pipeline/quotas", summary="Get API provider quota usage for active 30-day period")
def get_pipeline_quotas(
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from sqlalchemy import text as _text
    now = datetime.now(timezone.utc)

    rows = db.execute(
        _text("""
            SELECT DISTINCT ON (provider)
                provider, calls_made, quota_limit, period_end
            FROM api_usage_quota
            WHERE period_end IS NULL OR period_end > :now
            ORDER BY provider, period_start DESC NULLS LAST
        """),
        {"now": now},
    ).fetchall()

    result = []
    for r in rows:
        period_end = r.period_end
        days_until_reset = (
            max(0, (period_end - now).days) if period_end else None
        )
        pct = 0.0 if r.quota_limit == -1 else round(r.calls_made / max(r.quota_limit, 1) * 100, 1)
        result.append({
            "provider":         r.provider,
            "calls_made":       r.calls_made,
            "quota_limit":      r.quota_limit,
            "pct_used":         pct,
            "period_end":       period_end.isoformat() if period_end else None,
            "days_until_reset": days_until_reset,
        })
    return result


@router.get("/pipeline/web-validate/coverage", summary="Get matched vs unmatched vehicle coverage")
def get_web_validate_coverage(admin: AdminUser = Depends(require_admin)):
    from matcher import _norm_model_key as _nk

    # Load vehicle_years (all combos with engine and fuel details)
    veh = pd.read_sql(
        "SELECT UPPER(TRIM(make)) AS make_n,"
        " model AS raw_model, year,"
        " engine_capacity, fuel"
        " FROM vehicle_years WHERE year IS NOT NULL",
        engine,
    )
    veh["model_n"] = veh["raw_model"].astype(str).apply(_nk)
    veh["year"]    = pd.to_numeric(veh["year"], errors="coerce")
    veh = veh.dropna(subset=["make_n", "model_n", "year"])
    veh["year"] = veh["year"].astype(int)

    combos = (
        veh.groupby(["make_n", "model_n", "year"], as_index=False)
        .agg({"engine_capacity": "first", "fuel": "first"})
    )

    # Load validated combos
    validated = pd.read_sql(
        "SELECT make_n, model_n, year FROM web_battery_validation", engine
    )
    validated["year"] = pd.to_numeric(validated["year"], errors="coerce").astype(int)
    validated["_matched"] = True

    merged = combos.merge(validated, on=["make_n", "model_n", "year"], how="left")
    total   = len(merged)
    matched = int(merged["_matched"].sum())

    unmatched_df = (
        merged[merged["_matched"].isna()]
        [["make_n", "model_n", "year", "engine_capacity", "fuel"]]
        .rename(columns={"engine_capacity": "engine_cc", "fuel": "fuel_type"})
        .sort_values(["make_n", "model_n", "year"])
    )

    # Bucket counts (5-year generation windows)
    import json as _json
    veh["bucket"]       = (veh["year"] // 5) * 5
    total_buckets       = int(veh.groupby(["make_n", "model_n", "bucket"]).ngroups)
    validated["bucket"] = (validated["year"] // 5) * 5
    resolved_buckets    = int(validated.groupby(["make_n", "model_n", "bucket"]).ngroups)

    # web_model_cache.json entry count
    web_cache_path = Path(__file__).parent / "cache" / "web_model_cache.json"
    try:
        with open(web_cache_path) as _f:
            web_cache_size = len(_json.load(_f))
    except Exception:
        web_cache_size = 0

    with engine.connect() as conn:
        master_count = conn.execute(
            text("SELECT COUNT(*) FROM web_battery_validation")
        ).scalar() or 0
        staging_count = conn.execute(
            text("SELECT COUNT(*) FROM web_battery_staging")
        ).scalar() or 0

    return {
        "total":              total,
        "matched":            matched,
        "unmatched":          total - matched,
        "pct_matched":        round(matched / total * 100, 1) if total else 0.0,
        "master_count":       master_count,
        "staging_count":      staging_count,
        "unmatched_vehicles": unmatched_df.astype(object).where(pd.notna(unmatched_df), None).to_dict(orient="records"),
        "total_buckets":      total_buckets,
        "resolved_buckets":   resolved_buckets,
        "remaining_buckets":  total_buckets - resolved_buckets,
        "web_cache_size":     web_cache_size,
    }


@router.get("/pipeline/web-validate/providers", summary="Provider configuration status")
def get_web_validate_providers(admin: AdminUser = Depends(require_admin)):
    """Returns which providers are configured (have API keys) and which are always available."""
    google_configured = bool(os.getenv("GOOGLE_SEARCH_API_KEY") and os.getenv("GOOGLE_SEARCH_CX"))
    tavily_configured = bool(os.getenv("TAVILY_API_KEY"))
    return [
        {"provider": "duckduckgo", "configured": True,             "always_available": True},
        {"provider": "google_cse", "configured": google_configured, "always_available": False},
        {"provider": "tavily",     "configured": tavily_configured, "always_available": False},
    ]


@router.get("/pipeline/web-validate/matched", summary="Paginated list of web-validated vehicles")
def get_web_validate_matched(
    page: int = 1,
    page_size: int = 50,
    search: str = "",
    admin: AdminUser = Depends(require_admin),
):
    from sqlalchemy import text as _text
    offset = (page - 1) * page_size
    like = f"%{search.upper()}%" if search else "%"

    with engine.connect() as conn:
        total = conn.execute(_text("""
            SELECT COUNT(*) FROM web_battery_validation
            WHERE (UPPER(make_n) LIKE :q OR UPPER(model_n) LIKE :q)
        """), {"q": like}).scalar() or 0

        rows = conn.execute(_text("""
            SELECT id, make_n, model_n, year, battery_code, ah, technology, source, validated_at
            FROM web_battery_validation
            WHERE (UPPER(make_n) LIKE :q OR UPPER(model_n) LIKE :q)
            ORDER BY make_n, model_n, year
            LIMIT :lim OFFSET :off
        """), {"q": like, "lim": page_size, "off": offset}).fetchall()

    return {
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "items":     [dict(r._mapping) for r in rows],
    }


class MasterEditBody(BaseModel):
    ah:           Optional[float] = None
    technology:   Optional[str]   = None
    battery_code: Optional[str]   = None
    scope:        str             = Field(default="single", pattern="^(single|bucket)$")


@router.patch("/pipeline/web-validate/master/{record_id}", summary="Edit a committed master record (single or 5-year bucket)")
def patch_master_record(
    record_id: int,
    body: MasterEditBody,
    admin: AdminUser = Depends(require_admin),
):
    from sqlalchemy import text as _text
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        row = conn.execute(_text(
            "SELECT make_n, model_n, year, battery_code, ah, technology"
            " FROM web_battery_validation WHERE id=:id"
        ), {"id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Record not found")

        new_bc   = body.battery_code if body.battery_code is not None else row.battery_code
        new_ah   = body.ah           if body.ah           is not None else row.ah
        new_tech = body.technology   if body.technology   is not None else row.technology

        if body.scope == "bucket":
            bucket_start = (row.year // 5) * 5
            bucket_end   = bucket_start + 4
            targets = conn.execute(_text(
                "SELECT id, year, battery_code, ah, technology FROM web_battery_validation"
                " WHERE make_n=:mn AND model_n=:mo AND year BETWEEN :ys AND :ye"
            ), {"mn": row.make_n, "mo": row.model_n, "ys": bucket_start, "ye": bucket_end}).fetchall()
        else:
            targets = conn.execute(_text(
                "SELECT id, year, battery_code, ah, technology FROM web_battery_validation WHERE id=:id"
            ), {"id": record_id}).fetchall()

        max_ver = conn.execute(_text(
            "SELECT COALESCE(MAX(version_number),0) FROM web_battery_validation_versions"
        )).scalar() or 0
        vid = str(uuid.uuid4())
        scope_note = (
            f"Bucket edit ({bucket_start}–{bucket_end}): {row.make_n} {row.model_n}"
            if body.scope == "bucket"
            else f"Manual edit: {row.make_n} {row.model_n} {row.year}"
        )
        conn.execute(_text(
            "INSERT INTO web_battery_validation_versions"
            " (id,version_number,committed_at,run_id,committed_count,removed_count,"
            "  conflict_count,committed_by,initiated_by,notes)"
            " VALUES (:vid,:vn,:now,NULL,:cnt,0,0,:by,:by,:notes)"
        ), {"vid": vid, "vn": max_ver + 1, "now": now, "by": admin.username,
            "cnt": len(targets), "notes": scope_note})

        new_vals = {"battery_code": new_bc, "ah": new_ah, "technology": new_tech}
        for t in targets:
            old_vals = {"battery_code": t.battery_code, "ah": t.ah, "technology": t.technology}
            conn.execute(_text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                " VALUES (:vid,:mn,:mo,:yr,'updated',:ov,:nv)"
            ), {"vid": vid, "mn": row.make_n, "mo": row.model_n, "yr": t.year,
                "ov": json.dumps(old_vals), "nv": json.dumps(new_vals)})
            conn.execute(_text(
                "UPDATE web_battery_validation"
                " SET battery_code=:bc, ah=:ah, technology=:tech, validated_at=:now, version_id=:vid"
                " WHERE id=:id"
            ), {"bc": new_bc, "ah": new_ah, "tech": new_tech, "now": now, "vid": vid, "id": t.id})

    return {"ok": True, "version_number": max_ver + 1, "rows_updated": len(targets)}


@router.delete("/pipeline/web-validate/master/{record_id}", summary="Delete a committed master record")
def delete_master_record(
    record_id: int,
    admin: AdminUser = Depends(require_admin),
):
    from sqlalchemy import text as _text
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        row = conn.execute(_text(
            "SELECT make_n, model_n, year, battery_code, ah, technology"
            " FROM web_battery_validation WHERE id=:id"
        ), {"id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Record not found")

        old_vals = {"battery_code": row.battery_code, "ah": row.ah, "technology": row.technology}
        max_ver = conn.execute(_text(
            "SELECT COALESCE(MAX(version_number),0) FROM web_battery_validation_versions"
        )).scalar() or 0
        vid = str(uuid.uuid4())
        conn.execute(_text(
            "INSERT INTO web_battery_validation_versions"
            " (id,version_number,committed_at,run_id,committed_count,removed_count,"
            "  conflict_count,committed_by,initiated_by,notes)"
            " VALUES (:vid,:vn,:now,NULL,0,1,0,:by,:by,:notes)"
        ), {"vid": vid, "vn": max_ver + 1, "now": now, "by": admin.username,
            "notes": f"Manual delete: {row.make_n} {row.model_n} {row.year}"})
        conn.execute(_text(
            "INSERT INTO web_battery_validation_changelog"
            " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
            " VALUES (:vid,:mn,:mo,:yr,'removed',:ov,NULL)"
        ), {"vid": vid, "mn": row.make_n, "mo": row.model_n, "yr": row.year,
            "ov": json.dumps(old_vals)})
        conn.execute(_text("DELETE FROM web_battery_validation WHERE id=:id"), {"id": record_id})

    return {"ok": True, "version_number": max_ver + 1}


@router.post("/pipeline/web-validate/reset-cache", summary="Delete the battery validate lookup cache file and all matched vehicle rows")
def reset_web_validate_cache(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    from sqlalchemy import text as _text
    cache_path = Path(__file__).parent / "cache" / "battery_validate_cache.json"
    file_deleted = False
    if cache_path.exists():
        cache_path.unlink()
        file_deleted = True

    result = db.execute(_text("DELETE FROM web_battery_validation"))
    db.commit()

    return {"deleted": file_deleted, "rows_cleared": result.rowcount}


# ---------------------------------------------------------------------------
# Staging area endpoints
# ---------------------------------------------------------------------------

@router.get("/pipeline/web-validate/staging", summary="Get staged vehicles pending validation review")
def get_staging_area(
    page: int = 1,
    page_size: int = 50,
    filter: str = "all",   # all | valid | invalid | conflicts
    admin: AdminUser = Depends(require_admin),
):
    offset = (page - 1) * page_size
    where_clause = ""
    if filter == "valid":
        where_clause = "WHERE is_valid = TRUE AND conflict = FALSE"
    elif filter == "invalid":
        where_clause = "WHERE is_valid = FALSE"
    elif filter == "conflicts":
        where_clause = "WHERE conflict = TRUE"

    with engine.connect() as conn:
        total_row = conn.execute(text("SELECT COUNT(*) FROM web_battery_staging")).scalar() or 0
        valid_count = conn.execute(
            text("SELECT COUNT(*) FROM web_battery_staging WHERE is_valid = TRUE AND conflict = FALSE")
        ).scalar() or 0
        invalid_count = conn.execute(
            text("SELECT COUNT(*) FROM web_battery_staging WHERE is_valid = FALSE")
        ).scalar() or 0
        conflict_count = conn.execute(
            text("SELECT COUNT(*) FROM web_battery_staging WHERE conflict = TRUE")
        ).scalar() or 0
        run_id_row = conn.execute(
            text("SELECT run_id FROM web_battery_staging LIMIT 1")
        ).scalar()

        rows = conn.execute(
            text(
                f"SELECT id, make_n, model_n, year, battery_code, ah, technology,"
                f" source, engine_cc, fuel_type, staged_at,"
                f" is_valid, invalid_reason, conflict, conflict_detail"
                f" FROM web_battery_staging {where_clause}"
                f" ORDER BY make_n, model_n, year"
                f" LIMIT :lim OFFSET :off"
            ),
            {"lim": page_size, "off": offset},
        ).fetchall()

    items = []
    for r in rows:
        item = dict(r._mapping)
        # Parse conflict_detail JSON string back to dict for the response
        if item.get("conflict_detail"):
            try:
                item["conflict_detail"] = json.loads(item["conflict_detail"])
            except Exception:
                pass
        items.append(item)

    return {
        "has_staging":    total_row > 0,
        "total":          total_row,
        "valid_count":    valid_count,
        "invalid_count":  invalid_count,
        "conflict_count": conflict_count,
        "run_id":         run_id_row,
        "page":           page,
        "page_size":      page_size,
        "items":          items,
    }


class PatchStagingRowBody(BaseModel):
    ah:         float | None = None
    technology: str   | None = None
    scope:      str          = "single"   # "single" | "bucket"


@router.patch("/pipeline/web-validate/staging/{row_id}", summary="Edit ah/technology on a staged row")
def patch_staging_row(
    row_id: int,
    body: PatchStagingRowBody,
    admin: AdminUser = Depends(require_admin),
):
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT * FROM web_battery_staging WHERE id = :id"),
            {"id": row_id},
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Staging row not found")

        row_dict = dict(row._mapping)
        ah           = body.ah         if body.ah         is not None else row_dict.get("ah")
        technology   = body.technology if body.technology is not None else row_dict.get("technology")
        battery_code = row_dict.get("battery_code")

        is_valid, invalid_reason = _validate_staging_row(ah, technology, battery_code)

        # Determine which rows to update
        if body.scope == "bucket":
            bucket_start = (row_dict["year"] // 5) * 5
            bucket_end   = bucket_start + 4
            target_ids = [
                r.id for r in conn.execute(
                    text(
                        "SELECT id FROM web_battery_staging"
                        " WHERE make_n = :make AND model_n = :model"
                        "   AND year BETWEEN :ys AND :ye"
                    ),
                    {"make": row_dict["make_n"], "model": row_dict["model_n"],
                     "ys": bucket_start, "ye": bucket_end},
                ).fetchall()
            ]
        else:
            target_ids = [row_id]

        for tid in target_ids:
            conn.execute(
                text(
                    "UPDATE web_battery_staging"
                    " SET ah = :ah, technology = :technology,"
                    "     is_valid = :is_valid, invalid_reason = :invalid_reason"
                    " WHERE id = :id"
                ),
                {"ah": ah, "technology": technology, "is_valid": is_valid,
                 "invalid_reason": invalid_reason, "id": tid},
            )

    updated = {
        "id":             row_dict["id"],
        "make_n":         row_dict["make_n"],
        "model_n":        row_dict["model_n"],
        "year":           row_dict["year"],
        "battery_code":   battery_code,
        "ah":             ah,
        "technology":     technology,
        "source":         row_dict.get("source"),
        "engine_cc":      row_dict.get("engine_cc"),
        "fuel_type":      row_dict.get("fuel_type"),
        "staged_at":      row_dict["staged_at"].isoformat() if hasattr(row_dict["staged_at"], "isoformat") else str(row_dict["staged_at"]),
        "is_valid":       is_valid,
        "invalid_reason": invalid_reason,
        "conflict":       row_dict.get("conflict", False),
        "conflict_detail": json.loads(row_dict["conflict_detail"]) if row_dict.get("conflict_detail") else None,
    }
    return updated


@router.get("/pipeline/web-validate/staging/pre-commit", summary="Re-run conflict detection against current master state")
def staging_pre_commit(admin: AdminUser = Depends(require_admin)):
    """Refresh conflict flags in staging table before the commit modal is shown."""
    with engine.begin() as conn:
        staging_rows = conn.execute(
            text(
                "SELECT run_id, make_n, model_n, year, ah, technology, source"
                " FROM web_battery_staging"
            )
        ).fetchall()

        if not staging_rows:
            return {"conflict_count": 0, "conflicts": []}

        run_id = staging_rows[0].run_id
        conflicts = []
        for r in staging_rows:
            existing = conn.execute(
                text(
                    "SELECT battery_code, ah, technology, source, run_id"
                    " FROM web_battery_validation"
                    " WHERE make_n=:mn AND model_n=:mo AND year=:yr"
                    "   AND run_id IS DISTINCT FROM :rid"
                ),
                {"mn": r.make_n, "mo": r.model_n, "yr": r.year, "rid": run_id},
            ).fetchone()

            conflict = False
            conflict_detail = None
            if existing:
                ah_diff = abs((existing.ah or 0) - (r.ah or 0)) > 5 if (existing.ah and r.ah) else False
                tech_diff = (existing.technology or "").upper() != (r.technology or "").upper()
                if ah_diff or tech_diff:
                    conflict = True
                    conflict_detail = json.dumps({
                        "current": {
                            "ah": existing.ah, "technology": existing.technology,
                            "source": existing.source, "run_id": existing.run_id,
                        },
                        "staged": {"ah": r.ah, "technology": r.technology, "source": r.source},
                    })

            conn.execute(
                text(
                    "UPDATE web_battery_staging SET conflict=:cf, conflict_detail=:cd"
                    " WHERE make_n=:mn AND model_n=:mo AND year=:yr"
                ),
                {"cf": conflict, "cd": conflict_detail, "mn": r.make_n, "mo": r.model_n, "yr": r.year},
            )
            if conflict:
                conflicts.append({
                    "make_n": r.make_n, "model_n": r.model_n, "year": r.year,
                    "conflict_detail": json.loads(conflict_detail),
                })

    return {"conflict_count": len(conflicts), "conflicts": conflicts}


class ConflictResolution(BaseModel):
    make_n:  str
    model_n: str
    year:    int
    keep:    str   # "staging" | "current"


class CommitStagingBody(BaseModel):
    conflict_resolutions: list[ConflictResolution] = []


@router.post("/pipeline/web-validate/staging/commit", summary="Commit staged vehicles to master table")
def commit_staging(
    body: CommitStagingBody = Body(default_factory=CommitStagingBody),
    admin: AdminUser = Depends(require_admin),
):
    resolution_map: dict[tuple, str] = {
        (r.make_n, r.model_n, r.year): r.keep
        for r in body.conflict_resolutions
    }

    committed = removed_invalid = conflicts_resolved = 0
    changelog_entries: list[dict] = []

    with engine.begin() as conn:
        staging_rows = conn.execute(
            text(
                "SELECT run_id, make_n, model_n, year, battery_code, ah, technology,"
                " source, engine_cc, fuel_type, is_valid, conflict"
                " FROM web_battery_staging"
            )
        ).fetchall()

        if not staging_rows:
            raise HTTPException(status_code=400, detail="No staged data to commit")

        run_id = staging_rows[0].run_id

        # Determine next version number
        max_ver = conn.execute(
            text("SELECT COALESCE(MAX(version_number), 0) FROM web_battery_validation_versions")
        ).scalar() or 0
        version_number = max_ver + 1
        version_id = str(uuid.uuid4())

        now = datetime.now(timezone.utc)

        for r in staging_rows:
            key = (r.make_n, r.model_n, r.year)

            # Skip invalid rows from commit, but remove them from master if they're there
            if not r.is_valid:
                existing = conn.execute(
                    text(
                        "SELECT battery_code, ah, technology FROM web_battery_validation"
                        " WHERE make_n=:mn AND model_n=:mo AND year=:yr"
                    ),
                    {"mn": r.make_n, "mo": r.model_n, "yr": r.year},
                ).fetchone()
                if existing:
                    conn.execute(
                        text(
                            "DELETE FROM web_battery_validation"
                            " WHERE make_n=:mn AND model_n=:mo AND year=:yr"
                        ),
                        {"mn": r.make_n, "mo": r.model_n, "yr": r.year},
                    )
                    removed_invalid += 1
                    changelog_entries.append({
                        "version_id": version_id,
                        "make_n": r.make_n, "model_n": r.model_n, "year": r.year,
                        "change_type": "removed",
                        "old_values": json.dumps({
                            "battery_code": existing.battery_code,
                            "ah": existing.ah, "technology": existing.technology,
                        }),
                        "new_values": None,
                    })
                continue

            # For conflicts, check resolution
            if r.conflict:
                resolution = resolution_map.get(key, "staging")
                if resolution == "current":
                    conflicts_resolved += 1
                    continue  # keep master row unchanged

            # Upsert valid row into master
            existing = conn.execute(
                text(
                    "SELECT battery_code, ah, technology FROM web_battery_validation"
                    " WHERE make_n=:mn AND model_n=:mo AND year=:yr"
                ),
                {"mn": r.make_n, "mo": r.model_n, "yr": r.year},
            ).fetchone()

            change_type = "updated" if existing else "added"
            old_vals = json.dumps({
                "battery_code": existing.battery_code,
                "ah": existing.ah, "technology": existing.technology,
            }) if existing else None

            conn.execute(
                text(
                    "INSERT INTO web_battery_validation"
                    " (make_n, model_n, year, battery_code, ah, technology,"
                    "  source, engine_cc, fuel_type, validated_at, run_id, version_id)"
                    " VALUES"
                    " (:mn, :mo, :yr, :bc, :ah, :tech,"
                    "  :src, :ecc, :ft, :now, :rid, :vid)"
                    " ON CONFLICT (make_n, model_n, year) DO UPDATE SET"
                    "  battery_code=EXCLUDED.battery_code, ah=EXCLUDED.ah,"
                    "  technology=EXCLUDED.technology, source=EXCLUDED.source,"
                    "  engine_cc=EXCLUDED.engine_cc, fuel_type=EXCLUDED.fuel_type,"
                    "  validated_at=EXCLUDED.validated_at, run_id=EXCLUDED.run_id,"
                    "  version_id=EXCLUDED.version_id"
                ),
                {
                    "mn": r.make_n, "mo": r.model_n, "yr": r.year,
                    "bc": r.battery_code, "ah": r.ah, "tech": r.technology,
                    "src": r.source, "ecc": r.engine_cc, "ft": r.fuel_type,
                    "now": now, "rid": run_id, "vid": version_id,
                },
            )
            committed += 1
            if r.conflict:
                conflicts_resolved += 1

            changelog_entries.append({
                "version_id": version_id,
                "make_n": r.make_n, "model_n": r.model_n, "year": r.year,
                "change_type": change_type,
                "old_values": old_vals,
                "new_values": json.dumps({
                    "battery_code": r.battery_code,
                    "ah": r.ah, "technology": r.technology,
                }),
            })

        # Write version record
        conn.execute(
            text(
                "INSERT INTO web_battery_validation_versions"
                " (id, version_number, committed_at, run_id, committed_count, removed_count, conflict_count,"
                "  committed_by, initiated_by)"
                " VALUES (:id, :vn, :now, :rid, :cc, :rc, :cfc, :cby, :iby)"
            ),
            {
                "id": version_id, "vn": version_number, "now": now,
                "rid": run_id, "cc": committed, "rc": removed_invalid, "cfc": conflicts_resolved,
                "cby": admin.username,
                "iby": _pipeline_state.get("initiated_by"),
            },
        )

        # Write changelog entries
        for entry in changelog_entries:
            conn.execute(
                text(
                    "INSERT INTO web_battery_validation_changelog"
                    " (version_id, make_n, model_n, year, change_type, old_values, new_values)"
                    " VALUES (:vid, :mn, :mo, :yr, :ct, :ov, :nv)"
                ),
                {
                    "vid": entry["version_id"],
                    "mn": entry["make_n"], "mo": entry["model_n"], "yr": entry["year"],
                    "ct": entry["change_type"],
                    "ov": entry["old_values"], "nv": entry["new_values"],
                },
            )

        # Clear staging
        conn.execute(text("TRUNCATE web_battery_staging"))

    logger.info(
        "Staging committed by %s — version #%d: %d committed, %d removed, %d conflicts resolved",
        admin.username, version_number, committed, removed_invalid, conflicts_resolved,
    )
    return {
        "version_id":        version_id,
        "version_number":    version_number,
        "committed":         committed,
        "removed_invalid":   removed_invalid,
        "conflicts_resolved": conflicts_resolved,
        "committed_by":      admin.username,
        "initiated_by":      _pipeline_state.get("initiated_by"),
    }


@router.post("/pipeline/web-validate/staging/discard", summary="Discard staged vehicles and remove their master records")
def discard_staging(admin: AdminUser = Depends(require_admin)):
    with engine.begin() as conn:
        run_id_row = conn.execute(
            text("SELECT run_id FROM web_battery_staging LIMIT 1")
        ).scalar()

        if not run_id_row:
            conn.execute(text("TRUNCATE web_battery_staging"))
            return {"discarded": 0}

        result = conn.execute(
            text("DELETE FROM web_battery_validation WHERE run_id = :rid"),
            {"rid": run_id_row},
        )
        discarded = result.rowcount

        conn.execute(text("TRUNCATE web_battery_staging"))

    logger.info("Staging discarded by %s — %d master records removed", admin.username, discarded)
    return {"discarded": discarded}


# ---------------------------------------------------------------------------
# Fix suspicious Ah values in web-battery staging
# ---------------------------------------------------------------------------

_MAKE_MIN_AH: dict[str, int] = {
    "AUDI": 60, "BMW": 60, "MERCEDES": 70, "MERCEDES-BENZ": 70,
    "VOLKSWAGEN": 60, "PORSCHE": 70, "VOLVO": 60,
    "LAND ROVER": 70, "LANDROVER": 70, "JAGUAR": 60, "LEXUS": 60,
}
_KNOWN_BAD_AH = frozenset({28, 30, 37})
_GLOBAL_MIN_AH = 28


def _is_suspicious_ah(make_n: str, ah) -> bool:
    if ah is None:
        return False
    ah_int = int(ah)
    if ah_int < _GLOBAL_MIN_AH:
        return True
    if ah_int in _KNOWN_BAD_AH:
        return True
    floor = _MAKE_MIN_AH.get(make_n.upper())
    return bool(floor and ah_int < floor)


@router.post("/pipeline/web-validate/staging/fix-ah", summary="Auto-fix suspicious Ah values in staging via web lookup")
def fix_staging_ah(admin: AdminUser = Depends(require_admin)):
    from sqlalchemy import text as _text
    from pipelines.web_battery_validate import (
        _duckduckgo_lookup, _check_quota, _increment_quota, REQUEST_DELAY,
    )

    with engine.connect() as conn:
        rows = conn.execute(_text(
            "SELECT id, make_n, model_n, year, ah FROM web_battery_staging"
        )).fetchall()

    if not rows:
        return {"fixed": 0, "unchanged": 0, "failed": 0}

    fixed = unchanged = failed = 0

    for r in rows:
        if not _is_suspicious_ah(r.make_n, r.ah):
            continue

        result = None
        try:
            if _check_quota(engine, "duckduckgo"):
                result = _duckduckgo_lookup(r.make_n, r.model_n, r.year)
                if result:
                    _increment_quota(engine, "duckduckgo")
        except Exception as exc:
            logger.warning("DDG lookup failed for %s %s %s: %s", r.make_n, r.model_n, r.year, exc)

        if not result:
            try:
                from pipelines.web_battery_validate import _searxng_lookup
                if os.getenv("SEARXNG_URL") and _check_quota(engine, "searxng"):
                    result = _searxng_lookup(r.make_n, r.model_n, r.year)
                    if result:
                        _increment_quota(engine, "searxng")
            except Exception as exc:
                logger.warning("SearXNG lookup failed: %s", exc)

        if not result or result.get("ah") is None:
            failed += 1
            continue

        new_ah   = result["ah"]
        new_tech = result.get("technology") or "MF"

        if int(new_ah) == int(r.ah or 0):
            unchanged += 1
            continue

        is_valid = (20 <= new_ah <= 250)
        invalid_reason = None if is_valid else f"Ah out of range: {new_ah}"
        with engine.begin() as conn:
            conn.execute(_text(
                "UPDATE web_battery_staging SET ah=:ah, technology=:tech,"
                " is_valid=:iv, invalid_reason=:ir WHERE id=:id"
            ), {"ah": new_ah, "tech": new_tech, "iv": is_valid, "ir": invalid_reason, "id": r.id})
        fixed += 1
        time.sleep(REQUEST_DELAY)

    logger.info("fix-ah completed by %s: fixed=%d unchanged=%d failed=%d",
                admin.username, fixed, unchanged, failed)
    return {"fixed": fixed, "unchanged": unchanged, "failed": failed}


# ---------------------------------------------------------------------------
# Versioning endpoints
# ---------------------------------------------------------------------------

@router.get("/pipeline/web-validate/versions", summary="List all merge commit versions")
def get_versions(
    page: int = 1,
    page_size: int = 20,
    admin: AdminUser = Depends(require_admin),
):
    offset = (page - 1) * page_size
    with engine.connect() as conn:
        total = conn.execute(
            text("SELECT COUNT(*) FROM web_battery_validation_versions")
        ).scalar() or 0
        rows = conn.execute(
            text(
                "SELECT id, version_number, committed_at, run_id,"
                " committed_count, removed_count, conflict_count, notes,"
                " committed_by, initiated_by"
                " FROM web_battery_validation_versions"
                " ORDER BY version_number DESC"
                " LIMIT :lim OFFSET :off"
            ),
            {"lim": page_size, "off": offset},
        ).fetchall()
    return {
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "items":     [dict(r._mapping) for r in rows],
    }


@router.get("/pipeline/web-validate/versions/{version_id}/changelog", summary="Row-level changelog for a version")
def get_version_changelog(
    version_id: str,
    page: int = 1,
    page_size: int = 100,
    admin: AdminUser = Depends(require_admin),
):
    offset = (page - 1) * page_size
    with engine.connect() as conn:
        ver = conn.execute(
            text(
                "SELECT id, version_number, committed_at, committed_count,"
                " removed_count, conflict_count, committed_by, initiated_by"
                " FROM web_battery_validation_versions WHERE id = :vid"
            ),
            {"vid": version_id},
        ).fetchone()
        if not ver:
            raise HTTPException(status_code=404, detail="Version not found")

        total = conn.execute(
            text("SELECT COUNT(*) FROM web_battery_validation_changelog WHERE version_id = :vid"),
            {"vid": version_id},
        ).scalar() or 0

        rows = conn.execute(
            text(
                "SELECT make_n, model_n, year, change_type, old_values, new_values"
                " FROM web_battery_validation_changelog WHERE version_id = :vid"
                " ORDER BY change_type, make_n, model_n, year"
                " LIMIT :lim OFFSET :off"
            ),
            {"vid": version_id, "lim": page_size, "off": offset},
        ).fetchall()

    items = []
    for r in rows:
        item = dict(r._mapping)
        for key in ("old_values", "new_values"):
            if item[key]:
                try:
                    item[key] = json.loads(item[key])
                except Exception:
                    pass
        items.append(item)

    return {
        "version":   dict(ver._mapping),
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "items":     items,
    }


# ---------------------------------------------------------------------------
# Version revert endpoint
# ---------------------------------------------------------------------------

@router.post("/pipeline/web-validate/versions/{version_id}/revert", summary="Revert the master table to the state before a version's changes")
def revert_version(version_id: str, admin: AdminUser = Depends(require_admin)):
    with engine.connect() as conn:
        ver = conn.execute(
            text(
                "SELECT id, version_number, committed_count, removed_count, conflict_count"
                " FROM web_battery_validation_versions WHERE id = :vid"
            ),
            {"vid": version_id},
        ).fetchone()
        if not ver:
            raise HTTPException(status_code=404, detail="Version not found")

        changelog = conn.execute(
            text(
                "SELECT make_n, model_n, year, change_type, old_values, new_values"
                " FROM web_battery_validation_changelog WHERE version_id = :vid"
            ),
            {"vid": version_id},
        ).fetchall()

    if not changelog:
        raise HTTPException(status_code=400, detail="Version has no changelog entries — cannot revert")

    new_version_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    reverted = 0
    restored = 0
    revert_changelog: list[dict] = []

    with engine.begin() as conn:
        next_vn = (conn.execute(
            text("SELECT COALESCE(MAX(version_number), 0) + 1 FROM web_battery_validation_versions")
        ).scalar() or 1)

        for row in changelog:
            mn, mo, yr = row.make_n, row.model_n, row.year
            ct = row.change_type
            old_vals = json.loads(row.old_values) if row.old_values else {}
            new_vals = json.loads(row.new_values) if row.new_values else {}

            if ct == "added":
                # This row was added by the version — delete it to undo
                conn.execute(
                    text("DELETE FROM web_battery_validation WHERE make_n=:mn AND model_n=:mo AND year=:yr"),
                    {"mn": mn, "mo": mo, "yr": yr},
                )
                revert_changelog.append({
                    "version_id": new_version_id, "make_n": mn, "model_n": mo, "year": yr,
                    "change_type": "removed",
                    "old_values": row.new_values,
                    "new_values": None,
                })
                reverted += 1

            elif ct == "removed":
                # This row was deleted by the version — restore it from old_values
                conn.execute(
                    text(
                        "INSERT INTO web_battery_validation"
                        " (make_n, model_n, year, battery_code, ah, technology, source, validated_at, version_id)"
                        " VALUES (:mn, :mo, :yr, :bc, :ah, :tech, :src, :now, :vid)"
                        " ON CONFLICT (make_n, model_n, year) DO UPDATE SET"
                        "  battery_code=EXCLUDED.battery_code, ah=EXCLUDED.ah,"
                        "  technology=EXCLUDED.technology, source=EXCLUDED.source,"
                        "  validated_at=EXCLUDED.validated_at, version_id=EXCLUDED.version_id"
                    ),
                    {
                        "mn": mn, "mo": mo, "yr": yr,
                        "bc": old_vals.get("battery_code"), "ah": old_vals.get("ah"),
                        "tech": old_vals.get("technology"), "src": "reverted",
                        "now": now, "vid": new_version_id,
                    },
                )
                revert_changelog.append({
                    "version_id": new_version_id, "make_n": mn, "model_n": mo, "year": yr,
                    "change_type": "added",
                    "old_values": None,
                    "new_values": row.old_values,
                })
                restored += 1

            elif ct == "updated":
                # Restore the previous values
                conn.execute(
                    text(
                        "UPDATE web_battery_validation"
                        " SET battery_code=:bc, ah=:ah, technology=:tech,"
                        "     validated_at=:now, version_id=:vid"
                        " WHERE make_n=:mn AND model_n=:mo AND year=:yr"
                    ),
                    {
                        "bc": old_vals.get("battery_code"), "ah": old_vals.get("ah"),
                        "tech": old_vals.get("technology"),
                        "now": now, "vid": new_version_id,
                        "mn": mn, "mo": mo, "yr": yr,
                    },
                )
                revert_changelog.append({
                    "version_id": new_version_id, "make_n": mn, "model_n": mo, "year": yr,
                    "change_type": "updated",
                    "old_values": row.new_values,
                    "new_values": row.old_values,
                })
                reverted += 1

        total_changes = reverted + restored
        conn.execute(
            text(
                "INSERT INTO web_battery_validation_versions"
                " (id, version_number, committed_at, run_id, committed_count, removed_count,"
                "  conflict_count, committed_by, initiated_by, notes)"
                " VALUES (:id, :vn, :now, NULL, :cc, :rc, 0, :cby, NULL, :notes)"
            ),
            {
                "id": new_version_id, "vn": next_vn, "now": now,
                "cc": restored, "rc": reverted,
                "cby": admin.username,
                "notes": f"Revert of version #{ver.version_number}",
            },
        )

        for entry in revert_changelog:
            conn.execute(
                text(
                    "INSERT INTO web_battery_validation_changelog"
                    " (version_id, make_n, model_n, year, change_type, old_values, new_values)"
                    " VALUES (:vid, :mn, :mo, :yr, :ct, :ov, :nv)"
                ),
                {
                    "vid": entry["version_id"], "mn": entry["make_n"],
                    "mo": entry["model_n"], "yr": entry["year"],
                    "ct": entry["change_type"],
                    "ov": entry["old_values"], "nv": entry["new_values"],
                },
            )

    logger.info(
        "Version #%d reverted by %s — new version #%d: %d restored, %d removed",
        ver.version_number, admin.username, next_vn, restored, reverted,
    )
    return {
        "version_id":              new_version_id,
        "version_number":          next_vn,
        "reverted_version_number": ver.version_number,
        "committed_by":            admin.username,
        "changes":                 total_changes,
    }


# ---------------------------------------------------------------------------
# Staleness endpoint
# ---------------------------------------------------------------------------

@router.get("/pipeline/web-validate/staleness", summary="Check if vehicle data has changed since last pipeline run")
def get_pipeline_staleness(admin: AdminUser = Depends(require_admin)):
    with engine.connect() as conn:
        last_run_row = conn.execute(
            text(
                "SELECT finished_at FROM pipeline_run_log"
                " WHERE status = 'completed'"
                " ORDER BY finished_at DESC LIMIT 1"
            )
        ).fetchone()
        last_run_at = last_run_row.finished_at if last_run_row else None

        vehicles_updated_row = conn.execute(
            text("SELECT MAX(created_at) FROM vehicle_years")
        ).fetchone()
        vehicles_last_updated = vehicles_updated_row[0] if vehicles_updated_row else None

        # Count combos in vehicle_years not yet in web_battery_validation
        new_count_row = conn.execute(
            text(
                "SELECT COUNT(*) FROM ("
                "  SELECT UPPER(TRIM(make)) AS make_n,"
                "         model AS model_n, year"
                "  FROM vehicle_years WHERE year IS NOT NULL"
                "  GROUP BY UPPER(TRIM(make)), model, year"
                ") veh"
                " WHERE NOT EXISTS ("
                "  SELECT 1 FROM web_battery_validation wbv"
                "  WHERE wbv.make_n = veh.make_n"
                "    AND wbv.year = veh.year"
                " )"
            )
        ).scalar() or 0

        stale = bool(
            vehicles_last_updated and (
                last_run_at is None or vehicles_last_updated > last_run_at
            )
        )

    return {
        "last_run_completed_at":     last_run_at.isoformat() if last_run_at else None,
        "vehicles_last_updated_at":  vehicles_last_updated.isoformat() if vehicles_last_updated else None,
        "new_vehicles_since_last_run": int(new_count_row),
        "stale":                     stale,
    }


# ===========================================================================
# CRSP PIPELINE — run / staging / versioning / cache
# ===========================================================================

_crsp_lock = threading.Lock()
_crsp_state: dict = {
    "run_id":           None,
    "status":           "idle",   # idle | running | paused | done | cancelled | error
    "stage":            None,     # "dataprep" | "enrich"
    "current_make":     None,
    "current_model":    None,
    "total_models":     0,
    "processed_models": 0,
    "enriched_rows":    0,
    "source_counts":    {},
    "logs":             deque(maxlen=50),
    "started_at":       None,
    "finished_at":      None,
    "error_detail":     None,
    "cancel_event":     None,
    "pause_event":      None,
    "initiated_by":     None,
    "dataprep_result":  None,   # set by POST /pipeline/crsp/dataprep
    "unmatched_models": [],     # list[{make, model}] from last Stage 2 run
    "provider_details": {},     # {provider: {hits, cache_hits, rate_limits}}
}

# ---------------------------------------------------------------------------
# Fueleconomy.gov CSV download state  (POST /pipeline/crsp/fueleconomy/download)
# ---------------------------------------------------------------------------

_fe_download_state: dict = {
    "status":           "idle",   # idle | downloading | saving | done | cancelled | error
    "bytes_downloaded": 0,
    "total_bytes":      None,
    "records_saved":    0,
    "error":            None,
    "started_at":       None,
    "completed_at":     None,
    "cancel_event":     None,     # threading.Event — stripped before serialising
}
_fe_download_lock = threading.Lock()


def _run_fe_download(cancel_ev: threading.Event) -> None:
    from pipelines.enrich_years import FUELECONOMY_CSV_URL, FUELECONOMY_CSV, invalidate_fueleconomy_cache

    global _fe_download_state
    with _fe_download_lock:
        _fe_download_state.update({
            "status": "downloading",
            "bytes_downloaded": 0,
            "total_bytes": None,
            "records_saved": 0,
            "error": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
        })

    try:
        resp = requests.get(FUELECONOMY_CSV_URL, stream=True, timeout=180, verify=False)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0)) or None
        with _fe_download_lock:
            _fe_download_state["total_bytes"] = total

        chunks: list[bytes] = []
        downloaded = 0
        for chunk in resp.iter_content(chunk_size=65536):
            if cancel_ev.is_set():
                with _fe_download_lock:
                    _fe_download_state.update({
                        "status":       "cancelled",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    })
                return
            if chunk:
                chunks.append(chunk)
                downloaded += len(chunk)
                with _fe_download_lock:
                    _fe_download_state["bytes_downloaded"] = downloaded

        content = b"".join(chunks)

        # Parse CSV
        with _fe_download_lock:
            _fe_download_state["status"] = "saving"

        fe_df = pd.read_csv(
            io.BytesIO(content),
            usecols=["year", "make", "model"],
            dtype={"year": int, "make": str, "model": str},
        )

        # Bulk-save to DB
        db = SessionLocal()
        try:
            db.query(FueleconomyVehicle).delete()
            records = [
                {"year": int(r.year), "make": str(r.make), "model": str(r.model)}
                for r in fe_df.itertuples(index=False)
            ]
            db.bulk_insert_mappings(FueleconomyVehicle, records)

            # Update cache meta
            now = datetime.now(timezone.utc)
            meta = db.query(EnrichmentCacheMeta).filter_by(key="fueleconomy_csv").first()
            if meta is None:
                meta = EnrichmentCacheMeta(key="fueleconomy_csv")
                db.add(meta)
            meta.downloaded_at   = now
            meta.file_size_bytes = len(content)
            meta.record_count    = len(fe_df)
            meta.updated_at      = now
            db.commit()
        finally:
            db.close()

        # Also write local CSV for CLI backward compat
        os.makedirs("cache", exist_ok=True)
        with open(FUELECONOMY_CSV, "wb") as f:
            f.write(content)

        # Invalidate in-process DataFrame cache so next pipeline run reloads from DB
        invalidate_fueleconomy_cache()

        with _fe_download_lock:
            _fe_download_state.update({
                "status": "done",
                "records_saved": len(fe_df),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })

        logger.info("Fueleconomy CSV downloaded: %d records", len(fe_df))

    except Exception as exc:
        with _fe_download_lock:
            _fe_download_state.update({
                "status": "error",
                "error": str(exc),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
        logger.exception("Fueleconomy download failed: %s", exc)


# ---------------------------------------------------------------------------
# Background thread
# ---------------------------------------------------------------------------

def _crsp_thread(run_id: str, cancel_ev: threading.Event, pause_ev: threading.Event,
                 input_csv: str, initiated_by: str) -> None:
    from pipelines.enrich_years import main as _enrich_main

    def _log(line: str) -> None:
        with _crsp_lock:
            _crsp_state["logs"].append(line)
        logger.debug("[CRSP] %s", line)

    def _progress(processed: int, total: int, make: str, model: str) -> None:
        with _crsp_lock:
            _crsp_state["processed_models"] = processed
            _crsp_state["total_models"]     = total
            _crsp_state["current_make"]     = make
            _crsp_state["current_model"]    = model

    db = SessionLocal()
    try:
        with _crsp_lock:
            _crsp_state["stage"] = "enrich"

        result = _enrich_main(
            run_id=run_id,
            db=db,
            input_csv=input_csv,
            log_callback=_log,
            progress_callback=_progress,
            cancel_event=cancel_ev,
            pause_event=pause_ev,
        )

        with _crsp_lock:
            _crsp_state["status"]           = "cancelled" if cancel_ev.is_set() else "done"
            _crsp_state["enriched_rows"]    = result.get("expanded_rows", 0)
            _crsp_state["source_counts"]    = result.get("source_counts", {})
            _crsp_state["unmatched_models"] = result.get("unmatched_models", [])
            _crsp_state["provider_details"] = result.get("provider_details", {})
            _crsp_state["finished_at"]      = datetime.now(timezone.utc).isoformat()
            _crsp_state["error_detail"]     = None

    except InterruptedError:
        with _crsp_lock:
            _crsp_state["status"]       = "cancelled"
            _crsp_state["finished_at"]  = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        with _crsp_lock:
            _crsp_state["status"]       = "error"
            _crsp_state["finished_at"]  = datetime.now(timezone.utc).isoformat()
            _crsp_state["error_detail"] = str(exc)
        logger.exception("CRSP pipeline error: %s", exc)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Run / control endpoints
# ---------------------------------------------------------------------------

_CRSP_UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"


@router.post("/pipeline/crsp/upload", summary="Upload a raw CRSP Excel file for processing")
async def crsp_upload(
    file: UploadFile = File(...),
    admin: AdminUser = Depends(require_admin),
):
    _CRSP_UPLOAD_DIR.mkdir(exist_ok=True)
    suffix = Path(file.filename or "crsp.xlsx").suffix.lower()
    if suffix not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="Only .xlsx / .xls files are accepted")
    dest = _CRSP_UPLOAD_DIR / f"crsp_{uuid.uuid4().hex[:8]}{suffix}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    logger.info("CRSP file uploaded by %s → %s", admin.username, dest)
    return {"file_path": str(dest)}


# ---------------------------------------------------------------------------
# Validate uploaded Excel (before running dataprep)
# ---------------------------------------------------------------------------

class CrspValidateBody(BaseModel):
    file_path: str


@router.post("/pipeline/crsp/validate", summary="Validate a CRSP Excel file before running dataprep")
def validate_crsp_file(
    body: CrspValidateBody,
    admin: AdminUser = Depends(require_admin),
):
    p = Path(body.file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {body.file_path}")
    if p.suffix.lower() not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="Only .xlsx / .xls files are accepted")

    try:
        df = pd.read_excel(str(p), header=1)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read Excel file: {exc}")

    df.columns = df.columns.str.strip().str.lower().str.replace(r'[\s\n]+', '_', regex=True)
    columns_found = df.columns.tolist()

    required = ["make", "model"]
    optional_tracked = ["model_number", "engine_capacity", "fuel"]

    required_columns_present = {c: (c in columns_found) for c in required}
    optional_columns_found   = [c for c in optional_tracked if c in columns_found]
    total_rows = len(df)

    electric_vehicle_count = 0
    empty_make_count       = 0
    if "fuel" in columns_found:
        electric_vehicle_count = int(
            df["fuel"].astype(str).str.strip().str.lower().eq("electric").sum()
        )
    if "make" in columns_found:
        empty_make_count = int(
            df["make"].isna().sum()
            + df["make"].astype(str).str.strip().eq("").sum()
            + df["make"].astype(str).str.strip().str.lower().eq("nan").sum()
        )

    preview_cols = [c for c in ["make", "model", "engine_capacity", "fuel"] if c in columns_found]
    preview_rows = df[preview_cols].head(5).fillna("").astype(str).to_dict(orient="records")

    warnings: list[str] = []
    if not required_columns_present.get("make"):
        warnings.append("Required column 'make' is missing — dataprep will fail")
    if not required_columns_present.get("model"):
        warnings.append("Required column 'model' is missing — dataprep will fail")
    if total_rows < 20:
        warnings.append(f"Only {total_rows} rows — unusually small dataset, check the file")
    if total_rows > 50_000:
        warnings.append(f"{total_rows:,} rows — very large file, Stage 2 will take a long time")
    if electric_vehicle_count > 0:
        warnings.append(f"{electric_vehicle_count} electric vehicle rows will be rejected by Stage 1")
    if empty_make_count > 0:
        warnings.append(f"{empty_make_count} rows with empty 'make' will be rejected by Stage 1")
    if "fuel" not in columns_found:
        warnings.append("Optional column 'fuel' not found — electric vehicle filtering will be skipped")

    return {
        "columns_found":            columns_found,
        "required_columns_present": required_columns_present,
        "optional_columns_found":   optional_columns_found,
        "total_rows":               total_rows,
        "electric_vehicle_count":   electric_vehicle_count,
        "empty_make_count":         empty_make_count,
        "preview_rows":             preview_rows,
        "warnings":                 warnings,
    }


# ---------------------------------------------------------------------------
# Stage 1 — run dataprep synchronously
# ---------------------------------------------------------------------------

class CrspDataprepBody(BaseModel):
    file_path: str


@router.post("/pipeline/crsp/dataprep", summary="Run Stage 1 — clean and deduplicate CRSP Excel")
def run_crsp_dataprep(
    body: CrspDataprepBody,
    admin: AdminUser = Depends(require_admin),
):
    from pipelines.dataprep import main as _dataprep_main

    p = Path(body.file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {body.file_path}")

    logs: list[str] = []

    def _log(line: str) -> None:
        logs.append(line)

    try:
        result = _dataprep_main(str(p), log_callback=_log)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Dataprep failed: {exc}")

    if result.get("status") == "cancelled":
        raise HTTPException(status_code=409, detail="Dataprep was cancelled")

    with _crsp_lock:
        _crsp_state["dataprep_result"] = result

    logger.info(
        "CRSP dataprep completed by %s — %d clean rows, %d rejected, %d duplicates",
        admin.username, result["clean_rows"], result["rejected"], result["duplicates"],
    )
    return {**result, "logs": logs}


# ---------------------------------------------------------------------------
# Provider health check
# ---------------------------------------------------------------------------

@router.get("/pipeline/crsp/provider-health", summary="Check liveness of all external enrichment API endpoints")
def get_crsp_provider_health(admin: AdminUser = Depends(require_admin)):
    from pipelines.enrich_years import (
        FUELECONOMY_CSV_URL, NHTSA_ALL_MODELS, CARAPI_MODELS_URL,
        WIKI_SEARCH_URL, WIKIDATA_SPARQL, CARQUERY_URL,
    )

    # Use lightweight GET probes (stream=True so we never download the body).
    # HEAD is blocked by Wikipedia/Wikidata (403) and unsupported by NHTSA (405).
    # Use public endpoints that return 200 without authentication.
    providers = {
        "fueleconomy": "https://www.fueleconomy.gov/",
        "nhtsa":       NHTSA_ALL_MODELS.format(make="Toyota"),
        "carapi":      "https://carapi.app/api/makes",
        "carquery":    CARQUERY_URL + "?cmd=getMakes",
        "wikipedia":   WIKI_SEARCH_URL + "?action=query&format=json&list=search&srsearch=Toyota&srlimit=1",
        "wikidata":    WIKIDATA_SPARQL + "?query=ASK%7B%7D&format=json",
    }
    _headers = {"User-Agent": "BatteryFinderHealthCheck/1.0 (internal)"}

    results: dict = {}
    all_ok = True
    for name, url in providers.items():
        try:
            resp = requests.get(
                url, timeout=8, allow_redirects=True, verify=False,
                stream=True, headers=_headers,
            )
            resp.close()
            ok = resp.status_code < 400
            results[name] = {
                "url":         url,
                "ok":          ok,
                "status_code": resp.status_code,
                "error":       None if ok else f"HTTP {resp.status_code} {resp.reason}",
            }
        except Exception as exc:
            ok = False
            results[name] = {
                "url":         url,
                "ok":          False,
                "status_code": None,
                "error":       str(exc),
            }
        if not ok:
            all_ok = False

    results["checked_at"] = datetime.now(timezone.utc).isoformat()
    results["all_ok"]     = all_ok
    return results


# ---------------------------------------------------------------------------
# Unmatched models — read from DB + retry
# ---------------------------------------------------------------------------

@router.get("/pipeline/crsp/unmatched", summary="Get unmatched make+model pairs from the most recent Stage 2 run")
def get_crsp_unmatched(
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from models import VehicleYearUnmatched
    from sqlalchemy import text as sa_text

    with _crsp_lock:
        run_id = _crsp_state.get("run_id")

    # If no active run_id, fetch the latest run from DB
    if not run_id:
        row = db.execute(
            sa_text("SELECT run_id FROM vehicle_years_unmatched ORDER BY recorded_at DESC LIMIT 1")
        ).fetchone()
        run_id = row[0] if row else None

    if not run_id:
        return {"run_id": None, "count": 0, "unmatched_models": []}

    rows = (
        db.query(VehicleYearUnmatched)
        .filter(VehicleYearUnmatched.run_id == run_id)
        .order_by(VehicleYearUnmatched.make, VehicleYearUnmatched.model)
        .all()
    )
    return {
        "run_id":           run_id,
        "count":            len(rows),
        "unmatched_models": [{"make": r.make, "model": r.model, "fuel": r.fuel} for r in rows],
    }


@router.post("/pipeline/crsp/fueleconomy/download", summary="Download the fueleconomy.gov bulk CSV and store it in the DB")
def start_fueleconomy_download(admin: AdminUser = Depends(require_admin)):
    with _fe_download_lock:
        if _fe_download_state["status"] in ("downloading", "saving"):
            raise HTTPException(status_code=409, detail="Download already in progress")
    cancel_ev = threading.Event()
    with _fe_download_lock:
        _fe_download_state["cancel_event"] = cancel_ev
    t = threading.Thread(target=_run_fe_download, args=(cancel_ev,), daemon=True)
    t.start()
    return {"started": True}


@router.post("/pipeline/crsp/fueleconomy/cancel", summary="Cancel an in-progress fueleconomy.gov download")
def cancel_fueleconomy_download(admin: AdminUser = Depends(require_admin)):
    with _fe_download_lock:
        status    = _fe_download_state.get("status")
        cancel_ev = _fe_download_state.get("cancel_event")
    if status not in ("downloading", "saving"):
        raise HTTPException(status_code=409, detail="No active download to cancel")
    if cancel_ev:
        cancel_ev.set()
    return {"detail": "Cancel requested"}


@router.get("/pipeline/crsp/fueleconomy/download-status", summary="Poll fueleconomy.gov download progress")
def get_fueleconomy_download_status(admin: AdminUser = Depends(require_admin)):
    with _fe_download_lock:
        snap = dict(_fe_download_state)
    snap.pop("cancel_event", None)
    return snap


@router.post("/pipeline/crsp/rerun-unmatched", summary="Re-run Stage 2 enrichment on only the unmatched models from the last run")
def rerun_crsp_unmatched(
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from models import VehicleYearUnmatched
    from sqlalchemy import text as sa_text

    with _crsp_lock:
        if _crsp_state["status"] == "running":
            raise HTTPException(status_code=409, detail="CRSP pipeline is already running")
        current_run_id = _crsp_state.get("run_id")

    # Resolve latest run_id with unmatched rows
    if not current_run_id:
        row = db.execute(
            sa_text("SELECT run_id FROM vehicle_years_unmatched ORDER BY recorded_at DESC LIMIT 1")
        ).fetchone()
        current_run_id = row[0] if row else None

    if not current_run_id:
        raise HTTPException(status_code=400, detail="No unmatched models found — run Stage 2 first")

    rows = (
        db.query(VehicleYearUnmatched)
        .filter(VehicleYearUnmatched.run_id == current_run_id)
        .all()
    )
    if not rows:
        raise HTTPException(status_code=400, detail="No unmatched models to retry")

    # Write temp CSV with make, model, fuel columns for retry
    _CRSP_UPLOAD_DIR.mkdir(exist_ok=True)
    temp_csv = _CRSP_UPLOAD_DIR / f"unmatched_retry_{uuid.uuid4().hex[:8]}.csv"
    unmatched_df = pd.DataFrame(
        [{"make": r.make, "model": r.model, "fuel": r.fuel or ""} for r in rows]
    )
    unmatched_df.to_csv(str(temp_csv), index=False, encoding="utf-8")

    new_run_id = str(uuid.uuid4())
    cancel_ev  = threading.Event()
    pause_ev   = threading.Event()

    with _crsp_lock:
        _crsp_state.update({
            "run_id":           new_run_id,
            "status":           "running",
            "stage":            "enrich",
            "current_make":     None,
            "current_model":    None,
            "total_models":     0,
            "processed_models": 0,
            "enriched_rows":    0,
            "source_counts":    {},
            "logs":             deque(maxlen=50),
            "started_at":       datetime.now(timezone.utc).isoformat(),
            "finished_at":      None,
            "error_detail":     None,
            "cancel_event":     cancel_ev,
            "pause_event":      pause_ev,
            "initiated_by":     admin.username,
            "unmatched_models": [],
            "provider_details": {},
        })

    t = threading.Thread(
        target=_crsp_thread,
        args=(new_run_id, cancel_ev, pause_ev, str(temp_csv), admin.username),
        daemon=True,
        name=f"crsp-retry-{new_run_id[:8]}",
    )
    t.start()
    logger.info(
        "CRSP unmatched retry started by %s — %d pairs, run_id=%s",
        admin.username, len(rows), new_run_id,
    )
    return {"run_id": new_run_id, "retry_count": len(rows)}


class CrspRunBody(BaseModel):
    input_csv: str = Field(default="battery_lookup_dataset.csv")


@router.post("/pipeline/crsp/run", summary="Launch the CRSP year-enrichment pipeline")
def run_crsp_pipeline(
    body: CrspRunBody = Body(default_factory=CrspRunBody),
    admin: AdminUser = Depends(require_admin),
):
    with _crsp_lock:
        if _crsp_state["status"] == "running":
            raise HTTPException(status_code=409, detail="CRSP pipeline is already running")

        run_id    = str(uuid.uuid4())
        cancel_ev = threading.Event()
        pause_ev  = threading.Event()
        _crsp_state.update({
            "run_id":           run_id,
            "status":           "running",
            "stage":            None,
            "current_make":     None,
            "current_model":    None,
            "total_models":     0,
            "processed_models": 0,
            "enriched_rows":    0,
            "source_counts":    {},
            "logs":             deque(maxlen=50),
            "started_at":       datetime.now(timezone.utc).isoformat(),
            "finished_at":      None,
            "error_detail":     None,
            "cancel_event":     cancel_ev,
            "pause_event":      pause_ev,
            "initiated_by":     admin.username,
            "unmatched_models": [],
            "provider_details": {},
        })

    t = threading.Thread(
        target=_crsp_thread,
        args=(run_id, cancel_ev, pause_ev, body.input_csv, admin.username),
        daemon=True,
        name=f"crsp-{run_id[:8]}",
    )
    t.start()
    logger.info("CRSP pipeline started by %s run_id=%s", admin.username, run_id)
    return {"run_id": run_id}


@router.get("/pipeline/crsp/status", summary="Get CRSP pipeline status")
def get_crsp_status(admin: AdminUser = Depends(require_admin)):
    with _crsp_lock:
        state = dict(_crsp_state)
        state["logs"] = list(state["logs"])
        state.pop("cancel_event", None)
        state.pop("pause_event", None)
    return state


@router.post("/pipeline/crsp/pause", summary="Pause the running CRSP pipeline")
def pause_crsp(admin: AdminUser = Depends(require_admin)):
    with _crsp_lock:
        if _crsp_state["status"] != "running":
            raise HTTPException(status_code=400, detail="CRSP pipeline is not running")
        pause_ev = _crsp_state.get("pause_event")
        _crsp_state["status"] = "paused"
    if pause_ev:
        pause_ev.set()
    return {"detail": "Pause signal sent"}


@router.post("/pipeline/crsp/resume", summary="Resume a paused CRSP pipeline")
def resume_crsp(admin: AdminUser = Depends(require_admin)):
    with _crsp_lock:
        if _crsp_state["status"] != "paused":
            raise HTTPException(status_code=400, detail="CRSP pipeline is not paused")
        pause_ev = _crsp_state.get("pause_event")
        _crsp_state["status"] = "running"
    if pause_ev:
        pause_ev.clear()
    return {"detail": "Resume signal sent"}


@router.post("/pipeline/crsp/cancel", summary="Cancel the running CRSP pipeline")
def cancel_crsp(admin: AdminUser = Depends(require_admin)):
    with _crsp_lock:
        if _crsp_state["status"] not in ("running", "paused"):
            raise HTTPException(status_code=400, detail="CRSP pipeline is not running or paused")
        cancel_ev = _crsp_state.get("cancel_event")
        pause_ev  = _crsp_state.get("pause_event")

    if pause_ev:
        pause_ev.clear()
    if cancel_ev:
        cancel_ev.set()

    # Wait up to 3 s for thread to settle
    deadline = time.time() + 3.0
    while time.time() < deadline:
        with _crsp_lock:
            if _crsp_state["status"] not in ("running", "paused"):
                break
        time.sleep(0.1)

    with _crsp_lock:
        _crsp_state["status"] = "cancelled"

    logger.info("CRSP pipeline cancelled by %s", admin.username)
    return {"detail": "CRSP pipeline cancelled. Staged rows (if any) are now available for review."}


# ---------------------------------------------------------------------------
# Staging endpoints
# ---------------------------------------------------------------------------

@router.get("/pipeline/crsp/staging", summary="List staged vehicle_years rows pending review")
def get_crsp_staging(
    filter: str = "all",   # all | conflicts | new
    page: int = 1,
    page_size: int = 50,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(VehicleYearStaging)
    if filter == "conflicts":
        q = q.filter(VehicleYearStaging.conflict == 1)
    elif filter == "new":
        q = q.filter(VehicleYearStaging.conflict == 0, VehicleYearStaging.is_valid == 1)
    total = q.count()
    rows  = q.order_by(VehicleYearStaging.make, VehicleYearStaging.model, VehicleYearStaging.year) \
             .offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [
            {
                "id":              r.id,
                "run_id":          r.run_id,
                "make":            r.make,
                "model":           r.model,
                "year":            r.year,
                "engine_capacity": r.engine_capacity,
                "fuel":            r.fuel,
                "source":          r.source,
                "is_valid":        bool(r.is_valid),
                "invalid_reason":  r.invalid_reason,
                "conflict":        bool(r.conflict),
                "conflict_detail": json.loads(r.conflict_detail) if r.conflict_detail else None,
                "staged_at":       r.staged_at.isoformat() if r.staged_at else None,
            }
            for r in rows
        ],
    }


class PatchCrspStagingBody(BaseModel):
    engine_capacity: Optional[int] = None
    fuel:            Optional[str] = None


@router.patch("/pipeline/crsp/staging/{row_id}", summary="Edit engine_capacity or fuel on a staged row")
def patch_crsp_staging_row(
    row_id: int,
    body: PatchCrspStagingBody,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(VehicleYearStaging).filter(VehicleYearStaging.id == row_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Staged row not found")
    if body.engine_capacity is not None:
        row.engine_capacity = body.engine_capacity
    if body.fuel is not None:
        row.fuel = body.fuel
    db.commit()
    return {"detail": "Updated"}


@router.get("/pipeline/crsp/staging/pre-commit", summary="Re-run conflict detection against current vehicle_years")
def crsp_pre_commit(
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    staging_rows = db.query(VehicleYearStaging).all()
    existing = {
        (r.make, r.model, r.year): {"engine_capacity": r.engine_capacity, "fuel": r.fuel}
        for r in db.query(VehicleYear).all()
    }

    updated = 0
    for row in staging_rows:
        key     = (row.make, row.model, row.year)
        current = existing.get(key)
        if current is None:
            if row.conflict:
                row.conflict        = 0
                row.conflict_detail = None
                updated += 1
        else:
            ec_same   = current["engine_capacity"] == row.engine_capacity
            fuel_same = (current["fuel"] or "").lower() == (row.fuel or "").lower()
            now_conflict = not (ec_same and fuel_same)
            if now_conflict != bool(row.conflict):
                row.conflict = 1 if now_conflict else 0
                row.conflict_detail = json.dumps({
                    "current": current,
                    "staged": {"engine_capacity": row.engine_capacity, "fuel": row.fuel},
                }) if now_conflict else None
                updated += 1

    db.commit()
    total_conflicts = db.query(VehicleYearStaging).filter(VehicleYearStaging.conflict == 1).count()
    return {"rows_rescanned": len(staging_rows), "rows_updated": updated, "total_conflicts": total_conflicts}


class CrspConflictResolution(BaseModel):
    make:  str
    model: str
    year:  int
    resolution: str   # 'staged' | 'current'


class CommitCrspBody(BaseModel):
    conflict_resolutions: list[CrspConflictResolution] = []


@router.post("/pipeline/crsp/staging/commit", summary="Commit staged rows to vehicle_years")
def commit_crsp_staging(
    body: CommitCrspBody = Body(default_factory=CommitCrspBody),
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    staging_rows = db.query(VehicleYearStaging).all()
    if not staging_rows:
        raise HTTPException(status_code=400, detail="No staged rows to commit")

    version_id     = str(uuid.uuid4())
    version_number = (db.query(func.max(VehicleYearVersion.version_number)).scalar() or 0) + 1
    run_id         = staging_rows[0].run_id if staging_rows else None
    initiated_by   = _crsp_state.get("initiated_by")

    # Load ALL existing vehicle_years keys in one query — avoids N+1 selects
    existing_keys: set[tuple] = {
        (r.make, r.model, r.year)
        for r in db.execute(text("SELECT make, model, year FROM vehicle_years")).fetchall()
    }

    committed = skipped_existing = 0
    now = datetime.now(timezone.utc)

    # Insert the version row FIRST and flush it so the FK from vehicle_years_changelog
    # is satisfied before any changelog rows are written.
    version_row = VehicleYearVersion(
        id              = version_id,
        version_number  = version_number,
        committed_at    = now,
        run_id          = run_id,
        committed_count = 0,        # updated below after counting
        updated_count   = 0,
        removed_count   = 0,
        conflict_count  = 0,
        committed_by    = admin.username,
        initiated_by    = initiated_by,
    )
    db.add(version_row)
    db.flush()  # version must exist in DB before changelog FK references it

    for row in staging_rows:
        if (row.make, row.model, row.year) in existing_keys:
            skipped_existing += 1
            continue

        db.add(VehicleYear(
            make=row.make, model=row.model, year=row.year,
            engine_capacity=row.engine_capacity, fuel=row.fuel, source=row.source,
        ))
        db.add(VehicleYearChangelog(
            version_id  = version_id,
            make        = row.make,
            model       = row.model,
            year        = row.year,
            change_type = "added",
            old_values  = None,
            new_values  = json.dumps({
                "engine_capacity": row.engine_capacity,
                "fuel": row.fuel,
                "source": row.source,
            }),
        ))
        committed += 1

    # Update version row counts now that we know the final totals
    version_row.committed_count = committed
    version_row.conflict_count  = skipped_existing

    # Clear staging
    db.query(VehicleYearStaging).delete()
    db.commit()

    logger.info(
        "CRSP staging committed by %s — v%d added=%d skipped_existing=%d",
        admin.username, version_number, committed, skipped_existing,
    )
    return {
        "version_id":      version_id,
        "version_number":  version_number,
        "committed":       committed,
        "updated":         0,
        "conflict_kept":   skipped_existing,
        "skipped_existing": skipped_existing,
    }


@router.post("/pipeline/crsp/staging/discard", summary="Discard all staged rows without committing")
def discard_crsp_staging(
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    deleted = db.query(VehicleYearStaging).delete()
    db.commit()
    logger.info("CRSP staging discarded by %s (%d rows)", admin.username, deleted)
    return {"detail": f"Discarded {deleted} staged rows"}


# ---------------------------------------------------------------------------
# Version history endpoints
# ---------------------------------------------------------------------------

@router.get("/pipeline/crsp/versions", summary="List CRSP version history")
def get_crsp_versions(
    page: int = 1,
    page_size: int = 20,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total = db.query(VehicleYearVersion).count()
    rows  = db.query(VehicleYearVersion) \
              .order_by(VehicleYearVersion.version_number.desc()) \
              .offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "versions": [
            {
                "id":              v.id,
                "version_number":  v.version_number,
                "committed_at":    v.committed_at.isoformat() if v.committed_at else None,
                "run_id":          v.run_id,
                "committed_count": v.committed_count,
                "updated_count":   v.updated_count,
                "removed_count":   v.removed_count,
                "conflict_count":  v.conflict_count,
                "committed_by":    v.committed_by,
                "initiated_by":    v.initiated_by,
                "notes":           v.notes,
            }
            for v in rows
        ],
    }


@router.get("/pipeline/crsp/versions/{version_id}/changelog", summary="Row-level diffs for a version")
def get_crsp_version_changelog(
    version_id: str,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    version = db.query(VehicleYearVersion).filter(VehicleYearVersion.id == version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    entries = db.query(VehicleYearChangelog) \
                .filter(VehicleYearChangelog.version_id == version_id) \
                .order_by(VehicleYearChangelog.make, VehicleYearChangelog.model, VehicleYearChangelog.year) \
                .all()
    return {
        "version_id":     version_id,
        "version_number": version.version_number,
        "committed_at":   version.committed_at.isoformat() if version.committed_at else None,
        "committed_by":   version.committed_by,
        "entries": [
            {
                "id":          e.id,
                "make":        e.make,
                "model":       e.model,
                "year":        e.year,
                "change_type": e.change_type,
                "old_values":  json.loads(e.old_values) if e.old_values else None,
                "new_values":  json.loads(e.new_values) if e.new_values else None,
            }
            for e in entries
        ],
    }


@router.post("/pipeline/crsp/versions/{version_id}/revert", summary="Revert vehicle_years to state before this version")
def revert_crsp_version(
    version_id: str,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    version = db.query(VehicleYearVersion).filter(VehicleYearVersion.id == version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    entries = db.query(VehicleYearChangelog) \
                .filter(VehicleYearChangelog.version_id == version_id).all()

    new_version_id     = str(uuid.uuid4())
    new_version_number = (db.query(func.max(VehicleYearVersion.version_number)).scalar() or 0) + 1
    reverted = 0
    now      = datetime.now(timezone.utc)

    for entry in entries:
        existing = db.query(VehicleYear).filter(
            VehicleYear.make == entry.make,
            VehicleYear.model == entry.model,
            VehicleYear.year == entry.year,
        ).first()

        if entry.change_type == "added":
            # Reverse: delete the row
            if existing:
                db.delete(existing)
            db.add(VehicleYearChangelog(
                version_id=new_version_id, make=entry.make, model=entry.model, year=entry.year,
                change_type="removed",
                old_values=entry.new_values,
                new_values=None,
            ))
        elif entry.change_type == "removed":
            # Reverse: restore the row
            old = json.loads(entry.old_values) if entry.old_values else {}
            if not existing:
                db.add(VehicleYear(
                    make=entry.make, model=entry.model, year=entry.year,
                    engine_capacity=old.get("engine_capacity"),
                    fuel=old.get("fuel"),
                    source=old.get("source"),
                ))
            db.add(VehicleYearChangelog(
                version_id=new_version_id, make=entry.make, model=entry.model, year=entry.year,
                change_type="added",
                old_values=None,
                new_values=entry.old_values,
            ))
        elif entry.change_type == "updated":
            # Reverse: restore old values
            old = json.loads(entry.old_values) if entry.old_values else {}
            if existing:
                existing.engine_capacity = old.get("engine_capacity")
                existing.fuel            = old.get("fuel")
                existing.source          = old.get("source")
            db.add(VehicleYearChangelog(
                version_id=new_version_id, make=entry.make, model=entry.model, year=entry.year,
                change_type="updated",
                old_values=entry.new_values,
                new_values=entry.old_values,
            ))
        reverted += 1

    db.add(VehicleYearVersion(
        id              = new_version_id,
        version_number  = new_version_number,
        committed_at    = now,
        run_id          = None,
        committed_count = reverted,
        updated_count   = 0,
        removed_count   = 0,
        conflict_count  = 0,
        committed_by    = admin.username,
        initiated_by    = None,
        notes           = f"Revert of version #{version.version_number}",
    ))
    db.commit()

    logger.info(
        "CRSP version %s reverted by %s — new v%d, %d rows reversed",
        version_id, admin.username, new_version_number, reverted,
    )
    return {
        "reverted_version_id":     version_id,
        "reverted_version_number": version.version_number,
        "new_version_id":          new_version_id,
        "new_version_number":      new_version_number,
        "rows_reversed":           reverted,
    }


# ---------------------------------------------------------------------------
# Stats + cache endpoints
# ---------------------------------------------------------------------------

@router.get("/pipeline/crsp/stats", summary="DB counts for vehicle_years makes/models")
def get_crsp_stats(
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total_rows    = db.query(func.count(VehicleYear.id)).scalar() or 0
    total_makes   = db.query(func.count(func.distinct(VehicleYear.make))).scalar() or 0
    total_combos  = db.query(
        func.count(func.distinct(func.concat(VehicleYear.make, '|', VehicleYear.model)))
    ).scalar() or 0

    by_make_rows = db.execute(
        text(
            "SELECT make, "
            "       COUNT(DISTINCT model) AS model_count, "
            "       MIN(year) AS year_min, "
            "       MAX(year) AS year_max "
            "FROM vehicle_years "
            "GROUP BY make "
            "ORDER BY make"
        )
    ).fetchall()

    return {
        "total_rows":   total_rows,
        "total_makes":  total_makes,
        "total_combinations": total_combos,
        "staging_pending": db.query(func.count(VehicleYearStaging.id)).scalar() or 0,
        "by_make": [
            {
                "make":        r.make,
                "model_count": r.model_count,
                "year_min":    r.year_min,
                "year_max":    r.year_max,
            }
            for r in by_make_rows
        ],
    }


@router.get("/pipeline/crsp/cache-status", summary="Check age of enrichment cache datasets")
def get_crsp_cache_status(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    now  = datetime.now(timezone.utc)
    rows = db.query(EnrichmentCacheMeta).all()
    meta = {r.key: r for r in rows}

    def _age(key: str) -> dict:
        m = meta.get(key)
        if m is None or m.downloaded_at is None:
            return {"downloaded_at": None, "age_days": None, "file_size_bytes": None,
                    "record_count": None, "stale": False, "overdue": True}
        age_days = (now - m.downloaded_at).days
        return {
            "downloaded_at":   m.downloaded_at.isoformat(),
            "age_days":        age_days,
            "file_size_bytes": m.file_size_bytes,
            "record_count":    m.record_count,
            "stale":           age_days > 330,
            "overdue":         age_days > 365,
        }

    return {
        "fueleconomy_csv": _age("fueleconomy_csv"),
        "year_cache":      _age("year_cache"),
    }


@router.post("/pipeline/crsp/cache/refresh", summary="Clear the year enrichment cache to force re-lookup on next run")
def refresh_crsp_cache(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Clears cache/year_cache.json (NHTSA, CarAPI, and year lookup results).
    Does NOT touch fueleconomy data — the downloaded CSV and DB records are preserved.
    """
    results = []

    # Delete year_cache.json entirely so all NHTSA / CarAPI / year lookups are retried fresh
    cache_path = Path("cache/year_cache.json")
    if cache_path.exists():
        try:
            cache_path.unlink()
            results.append("Deleted cache/year_cache.json — all year lookups will be re-fetched on next run")
        except Exception as e:
            results.append(f"Could not delete year_cache.json: {e}")
    else:
        results.append("cache/year_cache.json not found (already absent)")

    # Reset only the year_cache meta timestamp; fueleconomy_csv is untouched
    now = datetime.now(timezone.utc)
    row = db.query(EnrichmentCacheMeta).filter(EnrichmentCacheMeta.key == "year_cache").first()
    if row:
        row.downloaded_at   = None
        row.file_size_bytes = None
        row.record_count    = None
        row.updated_at      = now
    db.commit()

    logger.info("CRSP year cache cleared by %s", admin.username)
    return {"detail": "Year cache cleared. fueleconomy data is untouched. Next Stage 2 run will re-fetch NHTSA, CarAPI and year lookups.", "actions": results}


# ===========================================================================
# VEHICLE EXPANSION PIPELINE — run / control / makes CRUD
# ===========================================================================

_expansion_lock = threading.Lock()
_expansion_state: dict = {
    "run_id":          None,
    "status":          "idle",   # idle | running | paused | done | cancelled | error
    "current_make":    None,
    "makes_total":     0,
    "makes_processed": 0,
    "rows_staged":     0,
    "rows_skipped":    0,
    "source_counts":   {},
    "logs":            deque(maxlen=50),
    "started_at":      None,
    "finished_at":     None,
    "error_detail":    None,
    "cancel_event":    None,
    "pause_event":     None,
    "initiated_by":    None,
}


def _expansion_thread(
    run_id: str, cancel_ev: threading.Event, pause_ev: threading.Event,
    target_makes: list[str] | None,
) -> None:
    from pipelines.vehicle_coverage_expansion import main as _run_expansion

    def _log(line: str) -> None:
        with _expansion_lock:
            _expansion_state["logs"].append(line)
        logger.debug("[Expansion] %s", line)

    def _progress(processed: int, total: int, make: str, source: str) -> None:
        with _expansion_lock:
            _expansion_state["makes_processed"] = processed
            _expansion_state["makes_total"]      = total
            _expansion_state["current_make"]     = make

    db = SessionLocal()
    try:
        result = _run_expansion(
            run_id=run_id,
            db=db,
            target_makes=target_makes,
            log_callback=_log,
            progress_callback=_progress,
            cancel_event=cancel_ev,
            pause_event=pause_ev,
        )
        staging = result.get("staging") or {}

        with _expansion_lock:
            _expansion_state["status"]         = "cancelled" if cancel_ev.is_set() else "done"
            _expansion_state["rows_staged"]     = staging.get("staged", 0)
            _expansion_state["rows_skipped"]    = staging.get("skipped_unchanged", 0)
            _expansion_state["source_counts"]   = result.get("source_counts", {})
            _expansion_state["finished_at"]     = datetime.now(timezone.utc).isoformat()
            _expansion_state["error_detail"]    = None

    except Exception as exc:
        with _expansion_lock:
            _expansion_state["status"]      = "error"
            _expansion_state["finished_at"] = datetime.now(timezone.utc).isoformat()
            _expansion_state["error_detail"] = str(exc)
        logger.exception("vehicle_coverage_expansion pipeline error: %s", exc)
    finally:
        db.close()


class ExpansionRunBody(BaseModel):
    target_makes: Optional[list[str]] = None  # None = all enabled makes


@router.post("/pipeline/expansion/run", summary="Launch the vehicle coverage expansion pipeline")
def run_expansion_pipeline(
    body: ExpansionRunBody = Body(default_factory=ExpansionRunBody),
    admin: AdminUser = Depends(require_admin),
):
    with _expansion_lock:
        if _expansion_state["status"] == "running":
            raise HTTPException(status_code=409, detail="Expansion pipeline is already running")

        run_id    = str(uuid.uuid4())
        cancel_ev = threading.Event()
        pause_ev  = threading.Event()
        _expansion_state.update({
            "run_id":          run_id,
            "status":          "running",
            "current_make":    None,
            "makes_total":     0,
            "makes_processed": 0,
            "rows_staged":     0,
            "rows_skipped":    0,
            "source_counts":   {},
            "logs":            deque(maxlen=50),
            "started_at":      datetime.now(timezone.utc).isoformat(),
            "finished_at":     None,
            "error_detail":    None,
            "cancel_event":    cancel_ev,
            "pause_event":     pause_ev,
            "initiated_by":    admin.username,
        })

    t = threading.Thread(
        target=_expansion_thread,
        args=(run_id, cancel_ev, pause_ev, body.target_makes),
        daemon=True,
        name=f"expansion-{run_id[:8]}",
    )
    t.start()
    logger.info("vehicle_coverage_expansion started by %s run_id=%s", admin.username, run_id)
    return {"run_id": run_id}


@router.get("/pipeline/expansion/status", summary="Get vehicle coverage expansion pipeline status")
def get_expansion_status(admin: AdminUser = Depends(require_admin)):
    with _expansion_lock:
        state = dict(_expansion_state)
        state["logs"] = list(state["logs"])
        state.pop("cancel_event", None)
        state.pop("pause_event", None)
    return state


@router.post("/pipeline/expansion/pause", summary="Pause the running expansion pipeline")
def pause_expansion(admin: AdminUser = Depends(require_admin)):
    with _expansion_lock:
        if _expansion_state["status"] != "running":
            raise HTTPException(status_code=400, detail="Expansion pipeline is not running")
        pause_ev = _expansion_state.get("pause_event")
        _expansion_state["status"] = "paused"
    if pause_ev:
        pause_ev.set()
    return {"detail": "Pause signal sent"}


@router.post("/pipeline/expansion/resume", summary="Resume a paused expansion pipeline")
def resume_expansion(admin: AdminUser = Depends(require_admin)):
    with _expansion_lock:
        if _expansion_state["status"] != "paused":
            raise HTTPException(status_code=400, detail="Expansion pipeline is not paused")
        pause_ev = _expansion_state.get("pause_event")
        _expansion_state["status"] = "running"
    if pause_ev:
        pause_ev.clear()
    return {"detail": "Resume signal sent"}


@router.post("/pipeline/expansion/cancel", summary="Cancel the running expansion pipeline")
def cancel_expansion(admin: AdminUser = Depends(require_admin)):
    with _expansion_lock:
        if _expansion_state["status"] not in ("running", "paused"):
            raise HTTPException(status_code=400, detail="Expansion pipeline is not running or paused")
        cancel_ev = _expansion_state.get("cancel_event")
        pause_ev  = _expansion_state.get("pause_event")

    if pause_ev:
        pause_ev.clear()
    if cancel_ev:
        cancel_ev.set()

    # Wait up to 3 s for thread to settle — the pipeline itself stages
    # whatever it collected so far before returning, so no separate
    # "populate staging" step is needed here (unlike web-validate).
    deadline = time.time() + 3.0
    while time.time() < deadline:
        with _expansion_lock:
            if _expansion_state["status"] not in ("running", "paused"):
                break
        time.sleep(0.1)

    with _expansion_lock:
        _expansion_state["status"] = "cancelled"

    logger.info("Expansion pipeline cancelled by %s", admin.username)
    return {"detail": "Expansion pipeline cancelled. Staged rows (if any) are now available for review."}


# ---------------------------------------------------------------------------
# Expansion makes CRUD
# ---------------------------------------------------------------------------

class ExpansionMakeBody(BaseModel):
    make:          str = Field(..., min_length=1, max_length=100)
    year_tier:     Literal["default", "commercial", "chinese"] = "default"
    nhtsa_slug:    Optional[str] = None
    cq_slug:       Optional[str] = None
    carsdata_slug: Optional[str] = None
    carinfo_slug:  Optional[str] = None
    enabled:       bool = True


class ExpansionMakePatchBody(BaseModel):
    make:          Optional[str] = Field(None, min_length=1, max_length=100)
    year_tier:     Optional[Literal["default", "commercial", "chinese"]] = None
    nhtsa_slug:    Optional[str] = None
    cq_slug:       Optional[str] = None
    carsdata_slug: Optional[str] = None
    carinfo_slug:  Optional[str] = None
    enabled:       Optional[bool] = None


def _serialize_expansion_make(m: ExpansionMake) -> dict:
    return {
        "id":            m.id,
        "make":          m.make,
        "year_tier":     m.year_tier,
        "nhtsa_slug":    m.nhtsa_slug,
        "cq_slug":       m.cq_slug,
        "carsdata_slug": m.carsdata_slug,
        "carinfo_slug":  m.carinfo_slug,
        "enabled":       m.enabled,
    }


@router.get("/pipeline/expansion/makes", summary="List all expansion pipeline target makes")
def list_expansion_makes(
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(ExpansionMake).order_by(ExpansionMake.make).all()
    return [_serialize_expansion_make(r) for r in rows]


@router.post("/pipeline/expansion/makes", status_code=201, summary="Add a new expansion pipeline target make")
def create_expansion_make(
    body: ExpansionMakeBody,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    make_upper = body.make.strip().upper()
    existing = db.query(ExpansionMake).filter(ExpansionMake.make == make_upper).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"'{make_upper}' already exists")

    row = ExpansionMake(
        make=make_upper,
        year_tier=body.year_tier,
        nhtsa_slug=body.nhtsa_slug,
        cq_slug=body.cq_slug,
        carsdata_slug=body.carsdata_slug,
        carinfo_slug=body.carinfo_slug,
        enabled=body.enabled,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    logger.info("Expansion make '%s' created by %s", make_upper, admin.username)
    return _serialize_expansion_make(row)


@router.patch("/pipeline/expansion/makes/{make_id}", summary="Update an expansion pipeline target make")
def update_expansion_make(
    make_id: int,
    body: ExpansionMakePatchBody,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(ExpansionMake).filter(ExpansionMake.id == make_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Expansion make not found")

    # exclude_unset: the frontend sends single-field bodies (e.g. just
    # {"enabled": false}) — a full dump would null out the other columns.
    updates = body.model_dump(exclude_unset=True)

    if "make" in updates:
        new_make = updates["make"].strip().upper()
        collision = (
            db.query(ExpansionMake)
            .filter(ExpansionMake.make == new_make, ExpansionMake.id != make_id)
            .first()
        )
        if collision:
            raise HTTPException(status_code=409, detail=f"'{new_make}' already exists")
        updates["make"] = new_make

    for field, value in updates.items():
        setattr(row, field, value)

    db.commit()
    db.refresh(row)

    logger.info("Expansion make '%s' (id=%d) updated by %s", row.make, make_id, admin.username)
    return _serialize_expansion_make(row)
