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
import time
from datetime import datetime, timezone
from typing import Optional

import matcher
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
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from models import AdminSession, AdminStats, AdminUser, BatteryAuditLog, BatterySpec
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
    from models import VehicleYear, VehicleRaw, ModelAlias

    counts = {
        "battery_specs":    db.query(func.count(BatterySpec.id)).filter(BatterySpec.deleted_at.is_(None)).scalar() or 0,
        "vehicle_years":    db.query(func.count(func.distinct(VehicleYear.make + '|' + VehicleYear.model))).scalar() or 0,
        "vehicles_raw":     db.query(func.count(VehicleRaw.id)).scalar() or 0,
        "model_aliases":    db.query(func.count(ModelAlias.id)).scalar() or 0,
    }

    reads_row = db.query(AdminStats).filter(AdminStats.stat_key == "db_reads").first()
    db_reads = reads_row.stat_value if reads_row else 0

    return {"counts": counts, "db_reads": db_reads}


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
    # Re-warm immediately
    matcher._vehicles()
    matcher._batteries()
    matcher._model_aliases()
    logger.info("Matcher cache refreshed by %s", admin.username)
    return {"detail": "Cache refreshed"}


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
