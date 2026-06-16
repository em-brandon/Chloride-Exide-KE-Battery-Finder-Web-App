"""
pipeline_app/app.py — Standalone Pipeline Dashboard Backend

Runs on port 8001, connects to the same PostgreSQL database as the main app.
Auth: POST /api/auth/login returns a Bearer token; all other routes require it.

Run:
    cd pipeline_app
    uvicorn app:app --port 8001 --reload
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow importing from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import pandas as pd
from fastapi import FastAPI, HTTPException, Depends, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from db import SessionLocal, engine
from admin_auth import (
    require_admin,
    create_session,
    set_session_cookie,
    clear_session_cookie,
    delete_session,
    verify_password,
)
from models import AdminUser, AdminSession

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pipeline_app")

# ---------------------------------------------------------------------------
# App + CORS
# ---------------------------------------------------------------------------

app = FastAPI(title="Battery Finder Pipeline Dashboard", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5175", "http://127.0.0.1:5175"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginBody, request: Request):
    db = SessionLocal()
    try:
        user = db.query(AdminUser).filter(AdminUser.username == body.username).first()
        if not user or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_session(db, user, request.client.host if request.client else None)
    finally:
        db.close()
    response = JSONResponse({"username": body.username})
    set_session_cookie(response, token)
    return response


@app.post("/api/auth/logout")
def logout(request: Request):
    token = request.cookies.get("admin_session")
    if token:
        db = SessionLocal()
        try:
            delete_session(db, token)
        finally:
            db.close()
    response = JSONResponse({"detail": "Logged out"})
    clear_session_cookie(response)
    return response


@app.get("/api/auth/me")
def me(admin: AdminUser = Depends(require_admin)):
    return {"username": admin.username}


@app.get("/api/auth/sessions")
def list_sessions(request: Request, admin: AdminUser = Depends(require_admin)):
    now = datetime.now(timezone.utc)
    current_token = request.cookies.get("admin_session")
    db = SessionLocal()
    try:
        sessions = (
            db.query(AdminSession)
            .filter(AdminSession.admin_id == admin.id, AdminSession.expires_at > now)
            .order_by(AdminSession.created_at.desc())
            .all()
        )
        return [
            {
                "id":         s.id,
                "created_at": s.created_at.isoformat(),
                "expires_at": s.expires_at.isoformat(),
                "ip_address": s.ip_address,
                "is_current": s.session_token == current_token,
            }
            for s in sessions
        ]
    finally:
        db.close()


@app.delete("/api/auth/sessions/{session_id}")
def revoke_session(session_id: int, request: Request, admin: AdminUser = Depends(require_admin)):
    current_token = request.cookies.get("admin_session")
    db = SessionLocal()
    try:
        session = (
            db.query(AdminSession)
            .filter(AdminSession.id == session_id, AdminSession.admin_id == admin.id)
            .first()
        )
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if session.session_token == current_token:
            raise HTTPException(status_code=400, detail="Cannot revoke current session — use logout")
        db.delete(session)
        db.commit()
    finally:
        db.close()
    return {"detail": "Session revoked"}


# ---------------------------------------------------------------------------
# Web-validate pipeline state
# ---------------------------------------------------------------------------

_wv_lock = threading.Lock()
_wv_state: dict = {
    "run_id":            None,
    "status":            "idle",
    "total":             0,
    "processed":         0,
    "found":             0,
    "not_found":         0,
    "current_provider":  None,
    "current_combo":     None,
    "provider_counts":   {"duckduckgo": 0, "searxng": 0, "brave": 0, "tavily": 0},
    "logs":              deque(maxlen=200),
    "started_at":        None,
    "phase1_total":      0,
    "phase1_processed":  0,
    "phase2_started_at": None,
    "finished_at":       None,
    "error_detail":      None,
    "cancel_event":      None,
    "pause_event":       None,
    "initiated_by":      None,
}


def _wv_thread(run_id: str, cancel_ev: threading.Event, pause_ev: threading.Event,
               enabled_providers, phase: str, username: str) -> None:
    from web_battery_validate import main as _run_wv

    def _progress(processed, total, provider, combo=""):
        with _wv_lock:
            _wv_state["processed"] = processed
            if total > 0:
                _wv_state["total"] = total
            _wv_state["current_provider"] = provider
            if combo:
                _wv_state["current_combo"] = combo
            if provider in _wv_state["provider_counts"]:
                _wv_state["provider_counts"][provider] = (_wv_state["provider_counts"].get(provider, 0) + 1)
            if _wv_state["phase2_started_at"] is None and processed > 0:
                _wv_state["phase2_started_at"] = datetime.now(timezone.utc).isoformat()

    def _log(msg: str, level: str = "info"):
        from datetime import datetime, timezone
        with _wv_lock:
            _wv_state["logs"].append({
                "level": level,
                "message": msg,
                "ts": datetime.now(timezone.utc).isoformat(),
            })

    def _phase1(fetched, total):
        with _wv_lock:
            _wv_state["phase1_processed"] = fetched
            _wv_state["phase1_total"]     = total

    try:
        result = _run_wv(cancel_ev, pause_ev, _progress, _log, enabled_providers, run_id,
                         phase1_progress_callback=_phase1, phase=phase)
        with _wv_lock:
            _wv_state["status"]          = "cancelled" if cancel_ev.is_set() else "done"
            _wv_state["found"]           = result.get("fetched", 0)
            _wv_state["not_found"]       = result.get("failed", 0)
            _wv_state["provider_counts"] = result.get("provider_counts", {})
            _wv_state["finished_at"]     = datetime.now(timezone.utc).isoformat()
            _wv_state["error_detail"]    = None
        # Populate staging after completion
        try:
            _populate_staging(run_id)
        except Exception as exc:
            logger.warning("Failed to populate staging: %s", exc)
    except Exception as exc:
        with _wv_lock:
            _wv_state["status"]       = "error"
            _wv_state["finished_at"]  = datetime.now(timezone.utc).isoformat()
            _wv_state["error_detail"] = str(exc)
        logger.exception("web_battery_validate error: %s", exc)


# ---------------------------------------------------------------------------
# Web-validate: run / status / pause / resume / cancel
# ---------------------------------------------------------------------------

class RunWVBody(BaseModel):
    enabled_providers: list[str] | None = None
    phase: str = "both"


@app.post("/api/pipeline/web-validate/run")
def wv_run(body: RunWVBody = RunWVBody(), admin: AdminUser = Depends(require_admin)):
    with _wv_lock:
        if _wv_state["status"] == "running":
            raise HTTPException(status_code=409, detail="Pipeline already running")
        run_id    = str(uuid.uuid4())
        cancel_ev = threading.Event()
        pause_ev  = threading.Event()
        _wv_state.update({
            "run_id": run_id, "status": "running",
            "total": 0, "processed": 0, "found": 0, "not_found": 0,
            "current_provider": None, "current_combo": None,
            "provider_counts": {"duckduckgo": 0, "searxng": 0, "brave": 0, "tavily": 0},
            "logs": deque(maxlen=200),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "phase1_total": 0, "phase1_processed": 0,
            "phase2_started_at": None, "finished_at": None,
            "error_detail": None,
            "cancel_event": cancel_ev, "pause_event": pause_ev,
            "initiated_by": admin.username,
        })
    threading.Thread(
        target=_wv_thread,
        args=(run_id, cancel_ev, pause_ev, body.enabled_providers, body.phase, admin.username),
        daemon=True,
    ).start()
    return {"run_id": run_id}


@app.get("/api/pipeline/web-validate/status")
def wv_status(admin: AdminUser = Depends(require_admin)):
    with _wv_lock:
        state = dict(_wv_state)
        state["logs"] = list(state["logs"])
        state.pop("cancel_event", None)
        state.pop("pause_event", None)
    return state


@app.post("/api/pipeline/web-validate/pause")
def wv_pause(admin: AdminUser = Depends(require_admin)):
    with _wv_lock:
        if _wv_state["status"] != "running":
            raise HTTPException(status_code=400, detail="Pipeline not running")
        ev = _wv_state.get("pause_event")
        _wv_state["status"] = "paused"
    if ev:
        ev.set()
    return {"detail": "Paused"}


@app.post("/api/pipeline/web-validate/resume")
def wv_resume(admin: AdminUser = Depends(require_admin)):
    with _wv_lock:
        if _wv_state["status"] != "paused":
            raise HTTPException(status_code=400, detail="Pipeline not paused")
        ev = _wv_state.get("pause_event")
        _wv_state["status"] = "running"
    if ev:
        ev.clear()
    return {"detail": "Resumed"}


@app.post("/api/pipeline/web-validate/cancel")
def wv_cancel(admin: AdminUser = Depends(require_admin)):
    with _wv_lock:
        if _wv_state["status"] not in ("running", "paused"):
            raise HTTPException(status_code=400, detail="Pipeline not running or paused")
        cancel_ev = _wv_state.get("cancel_event")
        pause_ev  = _wv_state.get("pause_event")
        run_id    = _wv_state.get("run_id")
    if pause_ev:
        pause_ev.clear()
    if cancel_ev:
        cancel_ev.set()
    deadline = time.time() + 3.0
    while time.time() < deadline:
        with _wv_lock:
            if _wv_state["status"] not in ("running", "paused"):
                break
        time.sleep(0.1)
    staged = invalid = conflicts = 0
    if run_id:
        try:
            staged, invalid, conflicts = _populate_staging(run_id)
        except Exception as exc:
            logger.warning("Staging populate failed: %s", exc)
    return {"detail": "Cancelled", "staged_count": staged, "invalid_count": invalid, "conflict_count": conflicts}


# ---------------------------------------------------------------------------
# Web-validate: providers / coverage / matched / reset-cache / staleness
# ---------------------------------------------------------------------------

@app.get("/api/pipeline/web-validate/providers")
def wv_providers(admin: AdminUser = Depends(require_admin)):
    return [
        {"provider": "duckduckgo", "configured": True,                                    "always_available": True},
        {"provider": "searxng",    "configured": bool(os.getenv("SEARXNG_URL")),          "always_available": False},
        {"provider": "brave",      "configured": bool(os.getenv("BRAVE_SEARCH_API_KEY")), "always_available": False},
        {"provider": "tavily",     "configured": bool(os.getenv("TAVILY_API_KEY")),       "always_available": False},
    ]


@app.get("/api/pipeline/web-validate/coverage")
def wv_coverage(admin: AdminUser = Depends(require_admin)):
    from matcher import _norm_model_key as _nk

    veh = pd.read_sql(
        "SELECT UPPER(TRIM(make)) AS make_n, model AS raw_model, year, engine_capacity, fuel"
        " FROM vehicle_years WHERE year IS NOT NULL", engine,
    )
    veh["model_n"] = veh["raw_model"].astype(str).apply(_nk)
    veh["year"]    = pd.to_numeric(veh["year"], errors="coerce")
    veh = veh.dropna(subset=["make_n", "model_n", "year"])
    veh["year"] = veh["year"].astype(int)

    combos = veh.groupby(["make_n", "model_n", "year"], as_index=False).agg({"engine_capacity": "first", "fuel": "first"})
    validated = pd.read_sql("SELECT make_n, model_n, year FROM web_battery_validation", engine)
    validated["year"]     = pd.to_numeric(validated["year"], errors="coerce").astype(int)
    validated["_matched"] = True

    merged  = combos.merge(validated, on=["make_n", "model_n", "year"], how="left")
    total   = len(merged)
    matched = int(merged["_matched"].sum())

    unmatched_df = (
        merged[merged["_matched"].isna()][["make_n", "model_n", "year", "engine_capacity", "fuel"]]
        .rename(columns={"engine_capacity": "engine_cc", "fuel": "fuel_type"})
        .sort_values(["make_n", "model_n", "year"])
    )

    veh["bucket"]      = (veh["year"] // 5) * 5
    total_buckets      = int(veh.groupby(["make_n", "model_n", "bucket"]).ngroups)
    validated["bucket"] = (validated["year"] // 5) * 5
    resolved_buckets    = int(validated.groupby(["make_n", "model_n", "bucket"]).ngroups)

    web_cache_path = Path(__file__).resolve().parent / "cache" / "web_model_cache.json"
    try:
        with open(web_cache_path) as f:
            web_cache_size = len(json.load(f))
    except Exception:
        web_cache_size = 0

    with engine.connect() as conn:
        master_count  = conn.execute(text("SELECT COUNT(*) FROM web_battery_validation")).scalar() or 0
        staging_count = conn.execute(text("SELECT COUNT(*) FROM web_battery_staging")).scalar()   or 0

    return {
        "total":              total,
        "matched":            matched,
        "unmatched":          total - matched,
        "pct_matched":        round(matched / total * 100, 1) if total else 0.0,
        "master_count":       master_count,
        "staging_count":      staging_count,
        "total_buckets":      total_buckets,
        "resolved_buckets":   resolved_buckets,
        "remaining_buckets":  total_buckets - resolved_buckets,
        "web_cache_size":     web_cache_size,
        "unmatched_vehicles": unmatched_df.astype(object).where(pd.notna(unmatched_df), None).to_dict(orient="records"),
    }


@app.get("/api/pipeline/web-validate/matched")
def wv_matched(page: int = 1, page_size: int = 50, search: str = "", admin: AdminUser = Depends(require_admin)):
    offset = (page - 1) * page_size
    like = f"%{search.upper()}%" if search else "%"
    with engine.connect() as conn:
        total = conn.execute(text(
            "SELECT COUNT(*) FROM web_battery_validation"
            " WHERE (UPPER(make_n) LIKE :q OR UPPER(model_n) LIKE :q)"
        ), {"q": like}).scalar() or 0
        rows = conn.execute(text(
            "SELECT id, make_n, model_n, year, battery_code, ah, technology, source, validated_at"
            " FROM web_battery_validation"
            " WHERE (UPPER(make_n) LIKE :q OR UPPER(model_n) LIKE :q)"
            " ORDER BY make_n, model_n, year LIMIT :lim OFFSET :off"
        ), {"q": like, "lim": page_size, "off": offset}).fetchall()
    return {"total": total, "page": page, "page_size": page_size, "items": [dict(r._mapping) for r in rows]}


@app.patch("/api/pipeline/web-validate/master/{record_id}")
def patch_master_record(record_id: int, body: MasterEditBody, admin: AdminUser = Depends(require_admin)):
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        row = conn.execute(text(
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
            targets = conn.execute(text(
                "SELECT id, year, battery_code, ah, technology FROM web_battery_validation"
                " WHERE make_n=:mn AND model_n=:mo AND year BETWEEN :ys AND :ye"
            ), {"mn": row.make_n, "mo": row.model_n, "ys": bucket_start, "ye": bucket_end}).fetchall()
        else:
            targets = conn.execute(text(
                "SELECT id, year, battery_code, ah, technology FROM web_battery_validation WHERE id=:id"
            ), {"id": record_id}).fetchall()

        max_ver = conn.execute(text(
            "SELECT COALESCE(MAX(version_number),0) FROM web_battery_validation_versions"
        )).scalar() or 0
        vid = str(uuid.uuid4())
        scope_note = (
            f"Bucket edit ({bucket_start}–{bucket_end}): {row.make_n} {row.model_n}"
            if body.scope == "bucket"
            else f"Manual edit: {row.make_n} {row.model_n} {row.year}"
        )
        conn.execute(text(
            "INSERT INTO web_battery_validation_versions"
            " (id,version_number,committed_at,run_id,committed_count,removed_count,"
            "  conflict_count,committed_by,initiated_by,notes)"
            " VALUES (:vid,:vn,:now,NULL,:cnt,0,0,:by,:by,:notes)"
        ), {"vid": vid, "vn": max_ver + 1, "now": now, "by": admin.username,
            "cnt": len(targets), "notes": scope_note})

        new_vals = {"battery_code": new_bc, "ah": new_ah, "technology": new_tech}
        for t in targets:
            old_vals = {"battery_code": t.battery_code, "ah": t.ah, "technology": t.technology}
            conn.execute(text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                " VALUES (:vid,:mn,:mo,:yr,'updated',:ov,:nv)"
            ), {"vid": vid, "mn": row.make_n, "mo": row.model_n, "yr": t.year,
                "ov": json.dumps(old_vals), "nv": json.dumps(new_vals)})
            conn.execute(text(
                "UPDATE web_battery_validation"
                " SET battery_code=:bc, ah=:ah, technology=:tech, validated_at=:now, version_id=:vid"
                " WHERE id=:id"
            ), {"bc": new_bc, "ah": new_ah, "tech": new_tech, "now": now, "vid": vid, "id": t.id})

    return {"ok": True, "version_number": max_ver + 1, "rows_updated": len(targets)}


@app.delete("/api/pipeline/web-validate/master/{record_id}")
def delete_master_record(record_id: int, admin: AdminUser = Depends(require_admin)):
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT make_n, model_n, year, battery_code, ah, technology"
            " FROM web_battery_validation WHERE id=:id"
        ), {"id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Record not found")
        old_vals = {"battery_code": row.battery_code, "ah": row.ah, "technology": row.technology}
        max_ver = conn.execute(text(
            "SELECT COALESCE(MAX(version_number),0) FROM web_battery_validation_versions"
        )).scalar() or 0
        vid = str(uuid.uuid4())
        conn.execute(text(
            "INSERT INTO web_battery_validation_versions"
            " (id,version_number,committed_at,run_id,committed_count,removed_count,"
            "  conflict_count,committed_by,initiated_by,notes)"
            " VALUES (:vid,:vn,:now,NULL,0,1,0,:by,:by,:notes)"
        ), {"vid": vid, "vn": max_ver + 1, "now": now, "by": admin.username,
            "notes": f"Manual delete: {row.make_n} {row.model_n} {row.year}"})
        conn.execute(text(
            "INSERT INTO web_battery_validation_changelog"
            " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
            " VALUES (:vid,:mn,:mo,:yr,'removed',:ov,NULL)"
        ), {"vid": vid, "mn": row.make_n, "mo": row.model_n, "yr": row.year,
            "ov": json.dumps(old_vals), "nv": None})
        conn.execute(text("DELETE FROM web_battery_validation WHERE id=:id"), {"id": record_id})
    return {"ok": True, "version_number": max_ver + 1}


@app.post("/api/pipeline/web-validate/reset-cache")
def wv_reset_cache(admin: AdminUser = Depends(require_admin)):
    cache_path = Path(__file__).resolve().parent / "cache" / "battery_validate_cache.json"
    deleted = False
    if cache_path.exists():
        cache_path.unlink()
        deleted = True
    with engine.begin() as conn:
        result = conn.execute(text("DELETE FROM web_battery_validation"))
    return {"deleted": deleted, "rows_cleared": result.rowcount}


@app.get("/api/pipeline/web-validate/staleness")
def wv_staleness(admin: AdminUser = Depends(require_admin)):
    with engine.connect() as conn:
        last_run = conn.execute(text(
            "SELECT finished_at FROM pipeline_run_log WHERE status='completed'"
            " ORDER BY finished_at DESC LIMIT 1"
        )).fetchone()
        last_run_at = last_run.finished_at if last_run else None
        veh_upd = conn.execute(text("SELECT MAX(created_at) FROM vehicle_years")).fetchone()
        veh_last = veh_upd[0] if veh_upd else None
        new_count = conn.execute(text(
            "SELECT COUNT(*) FROM ("
            "  SELECT UPPER(TRIM(make)) AS make_n, model AS model_n, year"
            "  FROM vehicle_years WHERE year IS NOT NULL GROUP BY 1,2,3"
            ") veh WHERE NOT EXISTS ("
            "  SELECT 1 FROM web_battery_validation wbv"
            "  WHERE wbv.make_n=veh.make_n AND wbv.year=veh.year"
            ")"
        )).scalar() or 0
        stale = bool(veh_last and (last_run_at is None or veh_last > last_run_at))
    return {
        "last_run_completed_at":      last_run_at.isoformat() if last_run_at else None,
        "vehicles_last_updated_at":   veh_last.isoformat() if veh_last else None,
        "new_vehicles_since_last_run": int(new_count),
        "stale": stale,
    }


# ---------------------------------------------------------------------------
# Quotas
# ---------------------------------------------------------------------------

@app.get("/api/pipeline/quotas")
def get_quotas(admin: AdminUser = Depends(require_admin)):
    now = datetime.now(timezone.utc)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT ON (provider)
                provider, calls_made, quota_limit, period_end
            FROM api_usage_quota
            WHERE period_end IS NULL OR period_end > :now
            ORDER BY provider, period_start DESC NULLS LAST
        """), {"now": now}).fetchall()
    result = []
    for r in rows:
        period_end = r.period_end
        days_until_reset = (
            max(0, (period_end - now).days) if period_end else None
        )
        result.append({
            "provider":         r.provider,
            "calls_made":       r.calls_made,
            "quota_limit":      r.quota_limit,
            "pct_used":         0.0 if r.quota_limit == -1
                                else round(r.calls_made / max(r.quota_limit, 1) * 100, 1),
            "period_end":       period_end.isoformat() if period_end else None,
            "days_until_reset": days_until_reset,
        })
    return result


# ---------------------------------------------------------------------------
# Staging helpers
# ---------------------------------------------------------------------------

_VALID_TECH = {"MF", "AGM", "EFB", "GEL", "WET"}


def _validate_row(ah, technology, battery_code) -> tuple[bool, str | None]:
    if battery_code is None:
        return False, "No battery code resolved"
    if ah is not None and (ah < 20 or ah > 250):
        return False, f"Ah out of range: {ah}"
    if technology is not None and technology.upper() not in _VALID_TECH:
        return False, f"Unknown technology: {technology}"
    return True, None


def _populate_staging(run_id: str) -> tuple[int, int, int]:
    staged = invalid = conflicts = 0
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT make_n, model_n, year, battery_code, ah, technology, source, engine_cc, fuel_type"
            " FROM web_battery_validation WHERE run_id=:rid"
        ), {"rid": run_id}).fetchall()
        if not rows:
            return 0, 0, 0
        conn.execute(text("TRUNCATE web_battery_staging"))
        for r in rows:
            is_valid, invalid_reason = _validate_row(r.ah, r.technology, r.battery_code)
            conflict = False
            conflict_detail = None
            existing = conn.execute(text(
                "SELECT battery_code, ah, technology, source, run_id FROM web_battery_validation"
                " WHERE make_n=:mn AND model_n=:mo AND year=:yr AND run_id IS DISTINCT FROM :rid"
            ), {"mn": r.make_n, "mo": r.model_n, "yr": r.year, "rid": run_id}).fetchone()
            if existing:
                ah_diff   = abs((existing.ah or 0) - (r.ah or 0)) > 5 if (existing.ah and r.ah) else False
                tech_diff = (existing.technology or "").upper() != (r.technology or "").upper()
                if ah_diff or tech_diff:
                    conflict = True
                    conflicts += 1
                    conflict_detail = json.dumps({
                        "current": {"ah": existing.ah, "technology": existing.technology,
                                    "source": existing.source, "run_id": existing.run_id},
                        "staged":  {"ah": r.ah, "technology": r.technology, "source": r.source},
                    })
            conn.execute(text(
                "INSERT INTO web_battery_staging"
                " (run_id, make_n, model_n, year, battery_code, ah, technology,"
                "  source, engine_cc, fuel_type, is_valid, invalid_reason, conflict, conflict_detail)"
                " VALUES (:rid,:mn,:mo,:yr,:bc,:ah,:tech,:src,:ecc,:ft,:iv,:ir,:cf,:cd)"
                " ON CONFLICT (make_n, model_n, year) DO UPDATE SET"
                "  run_id=EXCLUDED.run_id, battery_code=EXCLUDED.battery_code,"
                "  ah=EXCLUDED.ah, technology=EXCLUDED.technology, source=EXCLUDED.source,"
                "  engine_cc=EXCLUDED.engine_cc, fuel_type=EXCLUDED.fuel_type,"
                "  is_valid=EXCLUDED.is_valid, invalid_reason=EXCLUDED.invalid_reason,"
                "  conflict=EXCLUDED.conflict, conflict_detail=EXCLUDED.conflict_detail,"
                "  staged_at=now()"
            ), {"rid": run_id, "mn": r.make_n, "mo": r.model_n, "yr": r.year,
                "bc": r.battery_code, "ah": r.ah, "tech": r.technology,
                "src": r.source, "ecc": r.engine_cc, "ft": r.fuel_type,
                "iv": is_valid, "ir": invalid_reason, "cf": conflict, "cd": conflict_detail})
            staged += 1
            if not is_valid:
                invalid += 1
    return staged, invalid, conflicts


# ---------------------------------------------------------------------------
# Staging area endpoints
# ---------------------------------------------------------------------------

@app.get("/api/pipeline/web-validate/staging")
def get_staging(page: int = 1, page_size: int = 50, filter: str = "all", admin: AdminUser = Depends(require_admin)):
    offset = (page - 1) * page_size
    where = {
        "valid":     "WHERE is_valid=TRUE AND conflict=FALSE",
        "invalid":   "WHERE is_valid=FALSE",
        "conflicts": "WHERE conflict=TRUE",
    }.get(filter, "")
    with engine.connect() as conn:
        total         = conn.execute(text("SELECT COUNT(*) FROM web_battery_staging")).scalar() or 0
        valid_count   = conn.execute(text("SELECT COUNT(*) FROM web_battery_staging WHERE is_valid=TRUE AND conflict=FALSE")).scalar() or 0
        invalid_count = conn.execute(text("SELECT COUNT(*) FROM web_battery_staging WHERE is_valid=FALSE")).scalar() or 0
        conflict_count = conn.execute(text("SELECT COUNT(*) FROM web_battery_staging WHERE conflict=TRUE")).scalar() or 0
        run_id_row    = conn.execute(text("SELECT run_id FROM web_battery_staging LIMIT 1")).scalar()
        rows = conn.execute(text(
            f"SELECT id, make_n, model_n, year, battery_code, ah, technology,"
            f" source, engine_cc, fuel_type, staged_at,"
            f" is_valid, invalid_reason, conflict, conflict_detail"
            f" FROM web_battery_staging {where}"
            f" ORDER BY make_n, model_n, year LIMIT :lim OFFSET :off"
        ), {"lim": page_size, "off": offset}).fetchall()
    items = []
    for r in rows:
        item = dict(r._mapping)
        if item.get("conflict_detail"):
            try:
                item["conflict_detail"] = json.loads(item["conflict_detail"])
            except Exception:
                pass
        items.append(item)
    return {"has_staging": total > 0, "total": total, "valid_count": valid_count,
            "invalid_count": invalid_count, "conflict_count": conflict_count,
            "run_id": run_id_row, "page": page, "page_size": page_size, "items": items}


class PatchRowBody(BaseModel):
    ah:         float | None = None
    technology: str   | None = None


class MasterEditBody(BaseModel):
    ah:           float | None = None
    technology:   str   | None = None
    battery_code: str   | None = None
    scope:        str          = "single"  # "single" | "bucket"


@app.patch("/api/pipeline/web-validate/staging/{row_id}")
def patch_staging_row(row_id: int, body: PatchRowBody, admin: AdminUser = Depends(require_admin)):
    with engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM web_battery_staging WHERE id=:id"), {"id": row_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Row not found")
        row_dict     = dict(row._mapping)
        ah           = body.ah         if body.ah         is not None else row_dict.get("ah")
        technology   = body.technology if body.technology is not None else row_dict.get("technology")
        battery_code = row_dict.get("battery_code")
        is_valid, invalid_reason = _validate_row(ah, technology, battery_code)
        conn.execute(text(
            "UPDATE web_battery_staging SET ah=:ah, technology=:tech,"
            " is_valid=:iv, invalid_reason=:ir WHERE id=:id"
        ), {"ah": ah, "tech": technology, "iv": is_valid, "ir": invalid_reason, "id": row_id})
    row_dict.update({"ah": ah, "technology": technology, "is_valid": is_valid, "invalid_reason": invalid_reason})
    if row_dict.get("conflict_detail"):
        try:
            row_dict["conflict_detail"] = json.loads(row_dict["conflict_detail"])
        except Exception:
            pass
    if hasattr(row_dict.get("staged_at"), "isoformat"):
        row_dict["staged_at"] = row_dict["staged_at"].isoformat()
    return row_dict


@app.get("/api/pipeline/web-validate/staging/pre-commit")
def staging_pre_commit(admin: AdminUser = Depends(require_admin)):
    with engine.begin() as conn:
        staging_rows = conn.execute(text(
            "SELECT run_id, make_n, model_n, year, ah, technology, source FROM web_battery_staging"
        )).fetchall()
        if not staging_rows:
            return {"conflict_count": 0, "conflicts": []}
        run_id = staging_rows[0].run_id
        conflicts = []
        for r in staging_rows:
            existing = conn.execute(text(
                "SELECT battery_code, ah, technology, source, run_id FROM web_battery_validation"
                " WHERE make_n=:mn AND model_n=:mo AND year=:yr AND run_id IS DISTINCT FROM :rid"
            ), {"mn": r.make_n, "mo": r.model_n, "yr": r.year, "rid": run_id}).fetchone()
            conflict = False
            conflict_detail = None
            if existing:
                ah_diff   = abs((existing.ah or 0) - (r.ah or 0)) > 5 if (existing.ah and r.ah) else False
                tech_diff = (existing.technology or "").upper() != (r.technology or "").upper()
                if ah_diff or tech_diff:
                    conflict = True
                    conflict_detail = json.dumps({
                        "current": {"ah": existing.ah, "technology": existing.technology,
                                    "source": existing.source, "run_id": existing.run_id},
                        "staged":  {"ah": r.ah, "technology": r.technology, "source": r.source},
                    })
            conn.execute(text(
                "UPDATE web_battery_staging SET conflict=:cf, conflict_detail=:cd"
                " WHERE make_n=:mn AND model_n=:mo AND year=:yr"
            ), {"cf": conflict, "cd": conflict_detail, "mn": r.make_n, "mo": r.model_n, "yr": r.year})
            if conflict:
                conflicts.append({"make_n": r.make_n, "model_n": r.model_n, "year": r.year,
                                   "conflict_detail": json.loads(conflict_detail)})
    return {"conflict_count": len(conflicts), "conflicts": conflicts}


class ConflictResolution(BaseModel):
    make_n:  str
    model_n: str
    year:    int
    keep:    str  # "staging" | "current"


class CommitBody(BaseModel):
    conflict_resolutions: list[ConflictResolution] = []


@app.post("/api/pipeline/web-validate/staging/commit")
def commit_staging(body: CommitBody = CommitBody(), admin: AdminUser = Depends(require_admin)):
    resolution_map = {(r.make_n, r.model_n, r.year): r.keep for r in body.conflict_resolutions}
    committed = removed_invalid = conflicts_resolved = 0
    changelog_entries: list[dict] = []

    with engine.begin() as conn:
        staging_rows = conn.execute(text(
            "SELECT run_id, make_n, model_n, year, battery_code, ah, technology,"
            " source, engine_cc, fuel_type, is_valid, conflict FROM web_battery_staging"
        )).fetchall()
        if not staging_rows:
            raise HTTPException(status_code=400, detail="No staged data to commit")
        run_id = staging_rows[0].run_id
        max_ver = conn.execute(text(
            "SELECT COALESCE(MAX(version_number),0) FROM web_battery_validation_versions"
        )).scalar() or 0
        version_number = max_ver + 1
        version_id     = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        for r in staging_rows:
            key = (r.make_n, r.model_n, r.year)
            if not r.is_valid:
                ex = conn.execute(text(
                    "SELECT battery_code, ah, technology FROM web_battery_validation"
                    " WHERE make_n=:mn AND model_n=:mo AND year=:yr"
                ), {"mn": r.make_n, "mo": r.model_n, "yr": r.year}).fetchone()
                if ex:
                    conn.execute(text(
                        "DELETE FROM web_battery_validation WHERE make_n=:mn AND model_n=:mo AND year=:yr"
                    ), {"mn": r.make_n, "mo": r.model_n, "yr": r.year})
                    removed_invalid += 1
                    changelog_entries.append({
                        "version_id": version_id, "make_n": r.make_n, "model_n": r.model_n, "year": r.year,
                        "change_type": "removed",
                        "old_values": json.dumps({"battery_code": ex.battery_code, "ah": ex.ah, "technology": ex.technology}),
                        "new_values": None,
                    })
                continue
            if r.conflict:
                if resolution_map.get(key, "staging") == "current":
                    conflicts_resolved += 1
                    continue
            ex = conn.execute(text(
                "SELECT battery_code, ah, technology FROM web_battery_validation"
                " WHERE make_n=:mn AND model_n=:mo AND year=:yr"
            ), {"mn": r.make_n, "mo": r.model_n, "yr": r.year}).fetchone()
            change_type = "updated" if ex else "added"
            old_vals = json.dumps({"battery_code": ex.battery_code, "ah": ex.ah, "technology": ex.technology}) if ex else None
            conn.execute(text(
                "INSERT INTO web_battery_validation"
                " (make_n, model_n, year, battery_code, ah, technology,"
                "  source, engine_cc, fuel_type, validated_at, run_id, version_id)"
                " VALUES (:mn,:mo,:yr,:bc,:ah,:tech,:src,:ecc,:ft,:now,:rid,:vid)"
                " ON CONFLICT (make_n, model_n, year) DO UPDATE SET"
                "  battery_code=EXCLUDED.battery_code, ah=EXCLUDED.ah,"
                "  technology=EXCLUDED.technology, source=EXCLUDED.source,"
                "  engine_cc=EXCLUDED.engine_cc, fuel_type=EXCLUDED.fuel_type,"
                "  validated_at=EXCLUDED.validated_at, run_id=EXCLUDED.run_id,"
                "  version_id=EXCLUDED.version_id"
            ), {"mn": r.make_n, "mo": r.model_n, "yr": r.year,
                "bc": r.battery_code, "ah": r.ah, "tech": r.technology,
                "src": r.source, "ecc": r.engine_cc, "ft": r.fuel_type,
                "now": now, "rid": run_id, "vid": version_id})
            committed += 1
            if r.conflict:
                conflicts_resolved += 1
            changelog_entries.append({
                "version_id": version_id, "make_n": r.make_n, "model_n": r.model_n, "year": r.year,
                "change_type": change_type, "old_values": old_vals,
                "new_values": json.dumps({"battery_code": r.battery_code, "ah": r.ah, "technology": r.technology}),
            })
        conn.execute(text(
            "INSERT INTO web_battery_validation_versions"
            " (id, version_number, committed_at, run_id, committed_count, removed_count,"
            "  conflict_count, committed_by, initiated_by)"
            " VALUES (:id,:vn,:now,:rid,:cc,:rc,:cfc,:cby,:iby)"
        ), {"id": version_id, "vn": version_number, "now": now, "rid": run_id,
            "cc": committed, "rc": removed_invalid, "cfc": conflicts_resolved,
            "cby": admin.username, "iby": _wv_state.get("initiated_by")})
        for entry in changelog_entries:
            conn.execute(text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id, make_n, model_n, year, change_type, old_values, new_values)"
                " VALUES (:vid,:mn,:mo,:yr,:ct,:ov,:nv)"
            ), {"vid": entry["version_id"], "mn": entry["make_n"], "mo": entry["model_n"],
                "yr": entry["year"], "ct": entry["change_type"],
                "ov": entry["old_values"], "nv": entry["new_values"]})
        conn.execute(text("TRUNCATE web_battery_staging"))

    return {"version_id": version_id, "version_number": version_number,
            "committed": committed, "removed_invalid": removed_invalid,
            "conflicts_resolved": conflicts_resolved, "committed_by": admin.username}


@app.post("/api/pipeline/web-validate/staging/discard")
def discard_staging(admin: AdminUser = Depends(require_admin)):
    with engine.begin() as conn:
        run_id_row = conn.execute(text("SELECT run_id FROM web_battery_staging LIMIT 1")).scalar()
        if not run_id_row:
            conn.execute(text("TRUNCATE web_battery_staging"))
            return {"discarded": 0}
        result = conn.execute(text("DELETE FROM web_battery_validation WHERE run_id=:rid"), {"rid": run_id_row})
        discarded = result.rowcount
        conn.execute(text("TRUNCATE web_battery_staging"))
    return {"discarded": discarded}


# ---------------------------------------------------------------------------
# Fix suspicious Ah values in staging (Part 2 of plan)
# ---------------------------------------------------------------------------

MAKE_MIN_AH: dict[str, int] = {
    "AUDI": 60, "BMW": 60, "MERCEDES": 70, "MERCEDES-BENZ": 70,
    "VOLKSWAGEN": 60, "PORSCHE": 70, "VOLVO": 60,
    "LAND ROVER": 70, "LANDROVER": 70, "JAGUAR": 60, "LEXUS": 60,
}
KNOWN_BAD_AH = frozenset({28, 30, 37})
GLOBAL_MIN_AH = 28


def _is_suspicious(make_n: str, ah) -> bool:
    if ah is None:
        return False
    ah_int = int(ah)
    if ah_int < GLOBAL_MIN_AH:
        return True
    if ah_int in KNOWN_BAD_AH:
        return True
    floor = MAKE_MIN_AH.get(make_n.upper())
    if floor and ah_int < floor:
        return True
    return False


@app.post("/api/pipeline/web-validate/staging/fix-ah")
def fix_staging_ah(admin: AdminUser = Depends(require_admin)):
    from web_battery_validate import (
        _duckduckgo_lookup, _check_quota, _increment_quota,
        REQUEST_DELAY,
    )

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, make_n, model_n, year, ah FROM web_battery_staging"
        )).fetchall()

    if not rows:
        return {"fixed": 0, "unchanged": 0, "failed": 0}

    fixed     = 0
    unchanged = 0
    failed    = 0

    for r in rows:
        if not _is_suspicious(r.make_n, r.ah):
            continue

        result = None
        # Try DDG first (always available, no quota cost per spec)
        try:
            if _check_quota(engine, "duckduckgo"):
                result = _duckduckgo_lookup(r.make_n, r.model_n, r.year)
                if result:
                    _increment_quota(engine, "duckduckgo")
        except Exception as exc:
            logger.warning("DDG lookup failed for %s %s %s: %s", r.make_n, r.model_n, r.year, exc)

        # Fallback: SearXNG
        if not result:
            try:
                from web_battery_validate import _searxng_lookup
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

        is_valid, invalid_reason = _validate_row(new_ah, new_tech, None)
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE web_battery_staging SET ah=:ah, technology=:tech,"
                " is_valid=:iv, invalid_reason=:ir WHERE id=:id"
            ), {"ah": new_ah, "tech": new_tech, "iv": is_valid, "ir": invalid_reason, "id": r.id})
        fixed += 1
        time.sleep(REQUEST_DELAY)

    return {"fixed": fixed, "unchanged": unchanged, "failed": failed}


# ---------------------------------------------------------------------------
# Versioning endpoints
# ---------------------------------------------------------------------------

@app.get("/api/pipeline/web-validate/versions")
def get_versions(page: int = 1, page_size: int = 20, admin: AdminUser = Depends(require_admin)):
    offset = (page - 1) * page_size
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM web_battery_validation_versions")).scalar() or 0
        rows  = conn.execute(text(
            "SELECT id, version_number, committed_at, run_id, committed_count, removed_count,"
            " conflict_count, notes, committed_by, initiated_by"
            " FROM web_battery_validation_versions ORDER BY version_number DESC"
            " LIMIT :lim OFFSET :off"
        ), {"lim": page_size, "off": offset}).fetchall()
    return {"total": total, "page": page, "page_size": page_size, "items": [dict(r._mapping) for r in rows]}


@app.get("/api/pipeline/web-validate/versions/{version_id}/changelog")
def get_version_changelog(version_id: str, page: int = 1, page_size: int = 100,
                           admin: AdminUser = Depends(require_admin)):
    offset = (page - 1) * page_size
    with engine.connect() as conn:
        ver = conn.execute(text(
            "SELECT id, version_number, committed_at, committed_count, removed_count,"
            " conflict_count, committed_by, initiated_by"
            " FROM web_battery_validation_versions WHERE id=:vid"
        ), {"vid": version_id}).fetchone()
        if not ver:
            raise HTTPException(status_code=404, detail="Version not found")
        total = conn.execute(text(
            "SELECT COUNT(*) FROM web_battery_validation_changelog WHERE version_id=:vid"
        ), {"vid": version_id}).scalar() or 0
        rows = conn.execute(text(
            "SELECT make_n, model_n, year, change_type, old_values, new_values"
            " FROM web_battery_validation_changelog WHERE version_id=:vid"
            " ORDER BY change_type, make_n, model_n, year LIMIT :lim OFFSET :off"
        ), {"vid": version_id, "lim": page_size, "off": offset}).fetchall()
    items = []
    for r in rows:
        item = dict(r._mapping)
        for k in ("old_values", "new_values"):
            if item[k]:
                try:
                    item[k] = json.loads(item[k])
                except Exception:
                    pass
        items.append(item)
    return {"version": dict(ver._mapping), "total": total, "page": page, "page_size": page_size, "items": items}


@app.post("/api/pipeline/web-validate/versions/{version_id}/revert")
def revert_version(version_id: str, admin: AdminUser = Depends(require_admin)):
    with engine.connect() as conn:
        ver = conn.execute(text(
            "SELECT id, version_number, committed_count, removed_count FROM web_battery_validation_versions WHERE id=:vid"
        ), {"vid": version_id}).fetchone()
        if not ver:
            raise HTTPException(status_code=404, detail="Version not found")
        changelog = conn.execute(text(
            "SELECT make_n, model_n, year, change_type, old_values, new_values"
            " FROM web_battery_validation_changelog WHERE version_id=:vid"
        ), {"vid": version_id}).fetchall()
    if not changelog:
        raise HTTPException(status_code=400, detail="No changelog — cannot revert")

    new_vid = str(uuid.uuid4())
    now     = datetime.now(timezone.utc)
    reverted = restored = 0
    revert_cl: list[dict] = []

    with engine.begin() as conn:
        next_vn = (conn.execute(text(
            "SELECT COALESCE(MAX(version_number),0)+1 FROM web_battery_validation_versions"
        )).scalar() or 1)
        for row in changelog:
            mn, mo, yr = row.make_n, row.model_n, row.year
            old_vals = json.loads(row.old_values) if row.old_values else {}
            if row.change_type == "added":
                conn.execute(text("DELETE FROM web_battery_validation WHERE make_n=:mn AND model_n=:mo AND year=:yr"),
                             {"mn": mn, "mo": mo, "yr": yr})
                revert_cl.append({"version_id": new_vid, "make_n": mn, "model_n": mo, "year": yr,
                                   "change_type": "removed", "old_values": row.new_values, "new_values": None})
                reverted += 1
            elif row.change_type == "removed":
                conn.execute(text(
                    "INSERT INTO web_battery_validation"
                    " (make_n,model_n,year,battery_code,ah,technology,source,validated_at,version_id)"
                    " VALUES (:mn,:mo,:yr,:bc,:ah,:tech,'reverted',:now,:vid)"
                    " ON CONFLICT (make_n,model_n,year) DO UPDATE SET"
                    "  battery_code=EXCLUDED.battery_code,ah=EXCLUDED.ah,"
                    "  technology=EXCLUDED.technology,source=EXCLUDED.source,"
                    "  validated_at=EXCLUDED.validated_at,version_id=EXCLUDED.version_id"
                ), {"mn": mn, "mo": mo, "yr": yr,
                    "bc": old_vals.get("battery_code"), "ah": old_vals.get("ah"),
                    "tech": old_vals.get("technology"), "now": now, "vid": new_vid})
                revert_cl.append({"version_id": new_vid, "make_n": mn, "model_n": mo, "year": yr,
                                   "change_type": "added", "old_values": None, "new_values": row.old_values})
                restored += 1
            elif row.change_type == "updated":
                conn.execute(text(
                    "UPDATE web_battery_validation SET battery_code=:bc,ah=:ah,technology=:tech,"
                    " validated_at=:now,version_id=:vid WHERE make_n=:mn AND model_n=:mo AND year=:yr"
                ), {"bc": old_vals.get("battery_code"), "ah": old_vals.get("ah"),
                    "tech": old_vals.get("technology"), "now": now, "vid": new_vid,
                    "mn": mn, "mo": mo, "yr": yr})
                revert_cl.append({"version_id": new_vid, "make_n": mn, "model_n": mo, "year": yr,
                                   "change_type": "updated", "old_values": row.new_values, "new_values": row.old_values})
                reverted += 1
        conn.execute(text(
            "INSERT INTO web_battery_validation_versions"
            " (id,version_number,committed_at,run_id,committed_count,removed_count,"
            "  conflict_count,committed_by,initiated_by,notes)"
            " VALUES (:id,:vn,:now,NULL,:cc,:rc,0,:cby,NULL,:notes)"
        ), {"id": new_vid, "vn": next_vn, "now": now, "cc": restored, "rc": reverted,
            "cby": admin.username, "notes": f"Revert of version #{ver.version_number}"})
        for entry in revert_cl:
            conn.execute(text(
                "INSERT INTO web_battery_validation_changelog"
                " (version_id,make_n,model_n,year,change_type,old_values,new_values)"
                " VALUES (:vid,:mn,:mo,:yr,:ct,:ov,:nv)"
            ), {"vid": entry["version_id"], "mn": entry["make_n"], "mo": entry["model_n"],
                "yr": entry["year"], "ct": entry["change_type"],
                "ov": entry["old_values"], "nv": entry["new_values"]})

    return {"version_id": new_vid, "version_number": next_vn,
            "reverted_version_number": ver.version_number,
            "committed_by": admin.username, "changes": reverted + restored}


# ---------------------------------------------------------------------------
# CRSP pipeline state

# ---------------------------------------------------------------------------

_crsp_lock = threading.Lock()
_crsp_state: dict = {
    "status":      "idle",
    "stage":       None,
    "total_rows":  0,
    "clean_rows":  0,
    "rejected":    0,
    "duplicates":  0,
    "logs":        deque(maxlen=200),
    "started_at":  None,
    "finished_at": None,
    "error_detail": None,
    "cancel_event": None,
    "output_csv":  None,
}


def _crsp_thread(input_file: str, cancel_ev: threading.Event) -> None:
    from dataprep import main as _run_crsp

    def _log(line: str):
        with _crsp_lock:
            _crsp_state["logs"].append(line)

    def _progress(stage: str, current: int, total: int):
        with _crsp_lock:
            _crsp_state["stage"] = f"{stage} ({current}/{total})"

    try:
        result = _run_crsp(input_file, log_callback=_log, progress_callback=_progress, cancel_event=cancel_ev)
        with _crsp_lock:
            if result.get("status") == "cancelled":
                _crsp_state["status"] = "cancelled"
            else:
                _crsp_state.update({
                    "status":      "done",
                    "total_rows":  result.get("total_rows", 0),
                    "clean_rows":  result.get("clean_rows", 0),
                    "rejected":    result.get("rejected", 0),
                    "duplicates":  result.get("duplicates", 0),
                    "output_csv":  result.get("output_csv"),
                })
            _crsp_state["finished_at"]  = datetime.now(timezone.utc).isoformat()
            _crsp_state["error_detail"] = None
    except Exception as exc:
        with _crsp_lock:
            _crsp_state["status"]       = "error"
            _crsp_state["finished_at"]  = datetime.now(timezone.utc).isoformat()
            _crsp_state["error_detail"] = str(exc)
        logger.exception("CRSP pipeline error: %s", exc)


# ---------------------------------------------------------------------------
# CRSP endpoints
# ---------------------------------------------------------------------------

_UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"


@app.post("/api/pipeline/crsp/upload")
async def crsp_upload(file: UploadFile = File(...), admin: AdminUser = Depends(require_admin)):
    """Save uploaded XLSX to the uploads directory and return its server-side path."""
    _UPLOAD_DIR.mkdir(exist_ok=True)
    suffix = Path(file.filename or "crsp.xlsx").suffix.lower()
    if suffix not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="Only .xlsx / .xls files are accepted")
    dest = _UPLOAD_DIR / f"crsp_{uuid.uuid4().hex[:8]}{suffix}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"file_path": str(dest)}


class RunCRSPBody(BaseModel):
    input_file: str


@app.post("/api/pipeline/crsp/run")
def crsp_run(body: RunCRSPBody, admin: AdminUser = Depends(require_admin)):
    with _crsp_lock:
        if _crsp_state["status"] == "running":
            raise HTTPException(status_code=409, detail="CRSP pipeline already running")
        cancel_ev = threading.Event()
        _crsp_state.update({
            "status": "running", "stage": None,
            "total_rows": 0, "clean_rows": 0, "rejected": 0, "duplicates": 0,
            "logs": deque(maxlen=200),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None, "error_detail": None,
            "cancel_event": cancel_ev, "output_csv": None,
        })
    threading.Thread(target=_crsp_thread, args=(body.input_file, cancel_ev), daemon=True).start()
    return {"detail": "CRSP pipeline started"}


@app.get("/api/pipeline/crsp/status")
def crsp_status(admin: AdminUser = Depends(require_admin)):
    with _crsp_lock:
        state = dict(_crsp_state)
        state["logs"] = list(state["logs"])
        state.pop("cancel_event", None)
    return state


@app.post("/api/pipeline/crsp/cancel")
def crsp_cancel(admin: AdminUser = Depends(require_admin)):
    with _crsp_lock:
        if _crsp_state["status"] != "running":
            raise HTTPException(status_code=400, detail="CRSP pipeline not running")
        ev = _crsp_state.get("cancel_event")
    if ev:
        ev.set()
    return {"detail": "Cancel signal sent"}


# ---------------------------------------------------------------------------
# Static file serving (production web deployment)
# In dev the Vite dev server (port 5175) serves the frontend directly.
