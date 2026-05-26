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
