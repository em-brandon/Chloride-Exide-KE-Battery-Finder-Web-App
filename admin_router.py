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
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
from models import AdminSession, AdminStats, AdminUser, BatteryAuditLog, BatterySpec, UserFeedback, TestUser, TestUserSession
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
    from models import VehicleYear, VehicleRaw, ModelAlias

    inf_makes   = db.execute(text("SELECT COUNT(DISTINCT vehicle_type)  FROM dial_battery_inference")).scalar() or 0
    inf_models  = db.execute(text("SELECT COUNT(DISTINCT vehicle_model) FROM dial_battery_inference")).scalar() or 0
    inf_records = db.execute(text("SELECT COUNT(*)                      FROM dial_battery_inference")).scalar() or 0

    counts = {
        "battery_specs":    db.query(func.count(BatterySpec.id)).filter(BatterySpec.deleted_at.is_(None)).scalar() or 0,
        "vehicle_years":    db.query(func.count(func.distinct(VehicleYear.make + '|' + VehicleYear.model))).scalar() or 0,
        "vehicles_raw":     db.query(func.count(VehicleRaw.id)).scalar() or 0,
        "model_aliases":    db.query(func.count(ModelAlias.id)).scalar() or 0,
        "inference_makes":   inf_makes,
        "inference_models":  inf_models,
        "inference_records": inf_records,
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
    matcher._inference.cache_clear()
    # Re-warm immediately
    matcher._vehicles()
    matcher._batteries()
    matcher._model_aliases()
    matcher._inference()
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


# ---------------------------------------------------------------------------
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
    users = db.query(TestUser).order_by(TestUser.created_at.desc()).all()
    now = datetime.now(timezone.utc)
    return {
        "users": [
            {
                "id":         u.id,
                "username":   u.username,
                "email":      u.email,
                "created_at": u.created_at.isoformat(),
                "is_active":  bool(u.is_active),
                "active_sessions": db.query(TestUserSession).filter(
                    TestUserSession.user_id == u.id,
                    TestUserSession.expires_at > now,
                ).count(),
            }
            for u in users
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


@router.get("/pipeline/quotas", summary="Get API provider quota usage for current month")
def get_pipeline_quotas(
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from sqlalchemy import text as _text
    month = datetime.now(timezone.utc).strftime("%Y-%m")

    rows = db.execute(
        _text("SELECT provider, calls_made, quota_limit FROM api_usage_quota WHERE month = :m"),
        {"m": month},
    ).fetchall()

    result = []
    for provider, calls_made, quota_limit in rows:
        if quota_limit == -1:
            pct = 0.0
        else:
            pct = round(calls_made / max(quota_limit, 1) * 100, 1)
        result.append({
            "provider":    provider,
            "calls_made":  calls_made,
            "quota_limit": quota_limit,
            "pct_used":    pct,
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
            SELECT make_n, model_n, year, ah, technology, source, validated_at
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
        ah         = body.ah         if body.ah         is not None else row_dict.get("ah")
        technology = body.technology if body.technology is not None else row_dict.get("technology")
        battery_code = row_dict.get("battery_code")

        is_valid, invalid_reason = _validate_staging_row(ah, technology, battery_code)

        conn.execute(
            text(
                "UPDATE web_battery_staging"
                " SET ah = :ah, technology = :technology,"
                "     is_valid = :is_valid, invalid_reason = :invalid_reason"
                " WHERE id = :id"
            ),
            {"ah": ah, "technology": technology, "is_valid": is_valid,
             "invalid_reason": invalid_reason, "id": row_id},
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
