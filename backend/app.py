import logging
import os
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

import matcher
from admin_auth import _IS_SECURE
from admin_router import router as admin_router
from db import PublicSessionLocal, SessionLocal, engine
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from models import AdminStats, SearchEvent, TestUser, TestUserSession, UserFeedback
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

import bcrypt

logger = logging.getLogger("battery_finder")


# ------------------------------------------------------------------
# Read counter — in-memory accumulator flushed to DB every 60 seconds
# ------------------------------------------------------------------
_read_counter_lock = threading.Lock()
_read_counter_pending: int = 0
_READ_FLUSH_INTERVAL: int = 60  # seconds


def _flush_read_counter() -> None:
    """Write accumulated read count to admin_stats and reschedule."""
    global _read_counter_pending
    with _read_counter_lock:
        delta = _read_counter_pending
        _read_counter_pending = 0

    if delta > 0:
        try:
            db = PublicSessionLocal()
            row = db.query(AdminStats).filter(AdminStats.stat_key == "db_reads").first()
            if row:
                row.stat_value += delta
                row.updated_at = datetime.now(timezone.utc)
            else:
                db.add(AdminStats(
                    stat_key="db_reads",
                    stat_value=delta,
                    updated_at=datetime.now(timezone.utc),
                ))
            db.commit()
        except Exception as exc:
            logger.warning("Failed to flush read counter: %s", exc)
        finally:
            db.close()

    # Reschedule
    threading.Timer(_READ_FLUSH_INTERVAL, _flush_read_counter).start()


def _seconds_until_midnight() -> float:
    """Return the number of seconds until the next local midnight."""
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (tomorrow - now).total_seconds()


def _reset_daily_reads() -> None:
    """Reset the db_reads counter to 0 at midnight, then reschedule for next midnight."""
    try:
        db = PublicSessionLocal()
        row = db.query(AdminStats).filter(AdminStats.stat_key == "db_reads").first()
        if row:
            row.stat_value = 0
            row.updated_at = datetime.now(timezone.utc)
            db.commit()
        logger.info("Daily API reads counter reset at midnight.")
    except Exception as exc:
        logger.warning("Failed to reset daily reads counter: %s", exc)
    finally:
        db.close()

    # Also zero out any pending in-memory delta so it doesn't get added after reset
    global _read_counter_pending
    with _read_counter_lock:
        _read_counter_pending = 0

    # Reschedule for next midnight
    threading.Timer(_seconds_until_midnight(), _reset_daily_reads).start()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Verify DB connectivity, warm matcher cache, and start read counter flush timer."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("Database connection verified.")
    # Warm the in-process caches so the first request is not cold.
    matcher._vehicles()
    matcher._batteries()
    matcher._model_aliases()
    matcher._inference()
    matcher._fitment()
    logger.info("Matcher caches warmed.")
    # Start the background read-counter flush timer
    threading.Timer(_READ_FLUSH_INTERVAL, _flush_read_counter).start()
    logger.info("Read counter flush timer started (every %ds).", _READ_FLUSH_INTERVAL)
    # Schedule daily midnight reset of the API reads counter
    threading.Timer(_seconds_until_midnight(), _reset_daily_reads).start()
    logger.info("Daily reads reset scheduled (next midnight in %.0fs).", _seconds_until_midnight())
    # Load persisted maintenance mode state from DB
    from app_state import set_maintenance_mode
    from models import AppSettings
    with SessionLocal() as _db:
        _row = _db.query(AppSettings).filter_by(setting_key="maintenance_mode").first()
        if _row:
            set_maintenance_mode(_row.setting_value == "true")
    yield


app = FastAPI(title="Battery Finder API", version="1.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)

# CSP verified against the actual built frontend/dist output: no inline
# scripts, no data: image URIs — except react-country-flag (svg mode), which
# genuinely fetches flag images from the jsdelivr CDN at runtime. style-src
# needs 'unsafe-inline' because the frontend renders inline style={{}} props
# throughout rather than Tailwind utility classes (see CLAUDE.md).
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' https://cdn.jsdelivr.net; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "geolocation=(), camera=(), microphone=(), payment=(), usb=()"
    )
    response.headers["Content-Security-Policy"] = _CSP
    if _IS_SECURE:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


# CloudFront/ALB serve the built SPA and API same-origin in production, so no
# cross-origin origins are trusted unless explicitly configured — set
# ALLOWED_ORIGINS (comma-separated) to enable a genuine cross-origin caller.
_allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

# ------------------------------------------------------------------
# Admin router
# ------------------------------------------------------------------
app.include_router(admin_router)

# ------------------------------------------------------------------
# Rate limiting setup
# ------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    logger.warning("Validation error on %s: %s", request.url.path, errors)
    readable = "; ".join(
        f"{' -> '.join(str(l) for l in e['loc'])}: {e['msg']}" for e in errors
    )
    return JSONResponse(
        status_code=422,
        content={"detail": readable},
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(_request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Please try again later.",
            "retry_after": exc.args[0].replace("rate limit exceeded: ", ""),
        }
    )


# ------------------------------------------------------------------
# Maintenance mode middleware — runs outermost, intercepts every request
# ------------------------------------------------------------------
@app.middleware("http")
async def maintenance_mode_middleware(request: Request, call_next):
    from app_state import is_maintenance_mode
    if is_maintenance_mode():
        path = request.url.path
        # Admin API and admin frontend paths always pass through
        if not (path.startswith("/api/admin") or path.startswith("/admin") or path.startswith("/static/") or path.startswith("/assets/") or path == "/health"):
            _base = os.path.dirname(__file__)
            return FileResponse(
                os.path.join(_base, "static", "maintenance.html"),
                status_code=503,
            )
    return await call_next(request)


# ------------------------------------------------------------------
# Read counter middleware
# ------------------------------------------------------------------
@app.middleware("http")
async def count_reads_middleware(request: Request, call_next):
    """Increment the in-memory read counter for POST /api/recommend requests only.
    This tracks actual battery recommendation lookups made by end users."""
    global _read_counter_pending
    response = await call_next(request)
    if (
        request.method == "POST"
        and request.url.path == "/api/recommend"
    ):
        with _read_counter_lock:
            _read_counter_pending += 1
    return response


# ------------------------------------------------------------------
# Cache-Control headers for hashed static assets
# ------------------------------------------------------------------
@app.middleware("http")
async def cache_control_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


# ------------------------------------------------------------------
# Request schema
# ------------------------------------------------------------------
class RecommendRequest(BaseModel):
    make: str = Field(..., json_schema_extra={"example": "TOYOTA"})
    model: str = Field(..., json_schema_extra={"example": "Corolla"})
    year: int = Field(..., ge=1960, le=2030, json_schema_extra={"example": 2015})
    engine_cc: Optional[int] = Field(None, ge=500, le=8000, json_schema_extra={"example": 1500})
    fuel_type: Optional[str] = Field(None, json_schema_extra={"example": "Petrol"})
    stop_start: bool = Field(True, json_schema_extra={"example": True})
    input_type: Optional[str] = Field(None, pattern=r"^(select|type)$")


class FeedbackRequest(BaseModel):
    vehicle_label: str = Field(..., max_length=300)
    satisfaction: int = Field(..., ge=1, le=5)
    accuracy: Optional[str] = Field(None, pattern=r"^(exact|close|wrong|unsure)$")
    wrong_parts: Optional[dict] = Field(None)
    comments: Optional[str] = Field(None, max_length=400)
    submitted_at: str = Field(...)   # ISO-8601 string from client
    input_type: Optional[str] = Field(None, pattern=r"^(select|type)$")
    match_confidence: Optional[int] = Field(None, ge=0, le=100)
    match_type: Optional[str] = Field(None, max_length=50)
    recommended_battery: Optional[str] = Field(None, max_length=100)


# ── Test-user auth schemas ────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(..., min_length=6, max_length=100)
    email: Optional[str] = Field(None, max_length=255)


class LoginRequest(BaseModel):
    username: str = Field(..., max_length=100)
    password: str = Field(..., max_length=100)


# ── Test-user auth helpers ────────────────────────────────────────────────────

_TEST_SESSION_TTL_HOURS = 24


def _get_test_user_from_token(token: str | None, db) -> Optional[TestUser]:
    """Resolve a Bearer token to a TestUser, updating last_seen_at.  Returns None if invalid/expired."""
    if not token:
        return None
    session = (
        db.query(TestUserSession)
        .filter(TestUserSession.session_token == token)
        .first()
    )
    if not session:
        return None
    if session.expires_at < datetime.now(timezone.utc):
        return None
    session.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    user = db.query(TestUser).filter(TestUser.id == session.user_id).first()
    if not user or not user.is_active:
        return None
    return user


# ------------------------------------------------------------------
# API routes
# ------------------------------------------------------------------
@app.get("/health", summary="Unauthenticated liveness/readiness check for load balancer health checks")
@limiter.limit("60/minute")
def health_check(request: Request):
    """
    Minimal, unauthenticated DB-connectivity check for the ALB target group.

    Deliberately returns only {"status": ...} — the rich diagnostics
    (latency, pool usage) stay behind GET /api/admin/health so an anonymous
    caller can't get a free window into live DB load/timing.
    """
    assert request  # consumed by slowapi rate limiter
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "down"})


@app.get("/api/makes", summary="List all car makes")
@limiter.limit("20/minute")
def list_makes(request: Request):
    assert request  # consumed by slowapi rate limiter
    return {"makes": matcher.get_makes()}


@app.get("/api/models/{make}", summary="List models for a given make")
@limiter.limit("20/minute")
def list_models(request: Request, make: str):
    assert request  # consumed by slowapi rate limiter
    models = matcher.get_models(make)
    if not models:
        raise HTTPException(status_code=404, detail=f"No models found for make: {make}")
    return {"models": models}


@app.get("/api/years", summary="List available years for a given make and model")
@limiter.limit("20/minute")
def list_years(request: Request, make: str, model: str):
    assert request  # consumed by slowapi rate limiter
    years = matcher.get_years(make, model)
    if not years:
        raise HTTPException(status_code=404, detail=f"No years found for {make} {model}")
    return {"years": years}


def _log_search_event(
    make: Optional[str],
    model: Optional[str],
    year: Optional[int],
    engine_cc: Optional[int],
    fuel_type: Optional[str],
    battery_returned: Optional[str],
    battery_ah: Optional[int],
    match_type: Optional[str],
    confidence: Optional[int],
    matched: bool,
    ip_address: Optional[str] = None,
    input_type: Optional[str] = None,
) -> None:
    try:
        db = PublicSessionLocal()
        db.add(SearchEvent(
            timestamp        = datetime.now(timezone.utc),
            make             = make,
            model            = model,
            year             = year,
            engine_cc        = engine_cc,
            fuel_type        = fuel_type,
            battery_returned = battery_returned,
            battery_ah       = battery_ah,
            match_type       = match_type,
            confidence       = confidence,
            matched          = matched,
            ip_address       = ip_address,
            input_type       = input_type,
        ))
        db.commit()
    except Exception as exc:
        logger.debug("search_event log failed: %s", exc)
    finally:
        db.close()


@app.post("/api/recommend", summary="Get a battery recommendation")
@limiter.limit("10/minute")
def recommend(request: Request, req: RecommendRequest):
    assert request  # consumed by slowapi rate limiter
    result = matcher.recommend(
        req.make,
        req.model,
        req.year,
        req.engine_cc,
        req.fuel_type,
        stop_start=req.stop_start,
    )
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
    if ip:
        ip = ip.split(",")[0].strip()[:45]
    primary = result.get("primary") or {}
    threading.Thread(
        target=_log_search_event,
        args=(
            req.make,
            req.model,
            req.year,
            req.engine_cc,
            req.fuel_type,
            primary.get("battery_code"),
            primary.get("ah"),
            result.get("match_type"),
            result.get("confidence"),
            result.get("matched_make") is not None,
            ip,
            req.input_type,
        ),
        daemon=True,
    ).start()
    return result


@app.get("/api/batteries/search", summary="Search batteries by AH and/or CCA")
@limiter.limit("20/minute")
def search_batteries_by_specs(
    request: Request,
    ah:  Optional[float] = Query(None, ge=1,   le=300,  description="Target Ampere-hours"),
    cca: Optional[float] = Query(None, ge=1,   le=2000, description="Target Cold Cranking Amps"),
):
    assert request
    if ah is None and cca is None:
        raise HTTPException(status_code=422, detail="Provide at least one of: ah, cca")
    results = matcher.search_by_specs(ah=ah, cca=cca)
    return {"results": results, "count": len(results)}


@app.post("/api/feedback", summary="Submit user feedback on a battery recommendation", status_code=201)
@limiter.limit("5/minute")
def submit_feedback(request: Request, req: FeedbackRequest):
    assert request  # consumed by slowapi rate limiter
    import json as _json
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
    if ip:
        ip = ip.split(",")[0].strip()[:45]
    try:
        submitted_at = datetime.fromisoformat(req.submitted_at.replace("Z", "+00:00"))
    except ValueError:
        submitted_at = datetime.now(timezone.utc)

    # Resolve test user from Bearer token if present
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() or None

    db = PublicSessionLocal()
    try:
        test_user_id: Optional[int] = None
        if token:
            user = _get_test_user_from_token(token, db)
            if user:
                test_user_id = user.id

        row = UserFeedback(
            vehicle_label=req.vehicle_label,
            satisfaction=req.satisfaction,
            accuracy=req.accuracy or None,
            wrong_parts=_json.dumps(req.wrong_parts) if req.wrong_parts else None,
            comments=req.comments or None,
            submitted_at=submitted_at,
            ip_address=ip,
            test_user_id=test_user_id,
            input_type=req.input_type or None,
            match_confidence=req.match_confidence,
            match_type=req.match_type or None,
            recommended_battery=req.recommended_battery or None,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()
    return {"status": "ok"}


# ------------------------------------------------------------------
# Test-user auth routes
# ------------------------------------------------------------------

@app.post("/api/auth/register", summary="Register a new test user", status_code=201)
@limiter.limit("5/minute")
def register_test_user(request: Request, req: RegisterRequest):
    assert request
    db = PublicSessionLocal()
    try:
        existing = db.query(TestUser).filter(TestUser.username == req.username).first()
        if existing:
            raise HTTPException(status_code=409, detail="Username already taken.")
        if req.email:
            existing_email = db.query(TestUser).filter(TestUser.email == req.email).first()
            if existing_email:
                raise HTTPException(status_code=409, detail="Email already registered.")
        hashed = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt(rounds=12)).decode()
        user = TestUser(
            username=req.username,
            email=req.email or None,
            password_hash=hashed,
            created_at=datetime.now(timezone.utc),
            is_active=1,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"status": "ok", "user_id": user.id, "username": user.username}
    finally:
        db.close()


@app.post("/api/auth/login", summary="Log in as a test user")
@limiter.limit("10/minute")
def login_test_user(request: Request, req: LoginRequest):
    assert request
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
    if ip:
        ip = ip.split(",")[0].strip()[:45]
    user_agent = request.headers.get("User-Agent", "")[:300]

    db = PublicSessionLocal()
    try:
        user = db.query(TestUser).filter(TestUser.username == req.username).first()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password.")
        try:
            ok = bcrypt.checkpw(req.password.encode(), user.password_hash.encode())
        except Exception:
            ok = False
        if not ok:
            raise HTTPException(status_code=401, detail="Invalid username or password.")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account suspended.")

        token = secrets.token_hex(32)
        now = datetime.now(timezone.utc)
        session = TestUserSession(
            session_token=token,
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(hours=_TEST_SESSION_TTL_HOURS),
            ip_address=ip,
            user_agent=user_agent,
            last_seen_at=now,
        )
        db.add(session)
        db.commit()
        return {
            "token": token,
            "username": user.username,
            "user_id": user.id,
            "expires_at": session.expires_at.isoformat(),
        }
    finally:
        db.close()


@app.post("/api/auth/logout", summary="Log out a test user")
def logout_test_user(request: Request):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() or None
    if not token:
        return {"status": "ok"}
    db = SessionLocal()
    try:
        session = db.query(TestUserSession).filter(TestUserSession.session_token == token).first()
        if session:
            db.delete(session)
            db.commit()
    finally:
        db.close()
    return {"status": "ok"}


@app.get("/api/auth/me", summary="Get current test user info")
def me_test_user(request: Request):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() or None
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    db = PublicSessionLocal()
    try:
        user = _get_test_user_from_token(token, db)
        if not user:
            raise HTTPException(status_code=401, detail="Session expired or invalid.")
        return {"user_id": user.id, "username": user.username, "email": user.email}
    finally:
        db.close()


# ------------------------------------------------------------------
# Serve frontend — mount last so API routes take priority
# ------------------------------------------------------------------
dist_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
static_dir = os.path.join(os.path.dirname(__file__), "static")

_frontend_dir = dist_dir if os.path.isdir(dist_dir) else static_dir

# Catch-all: serve index.html for any non-API path (React Router SPA)
@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    _base = os.path.dirname(__file__)
    # Always serve files from static/ (maintenance assets must load even during maintenance mode)
    if full_path.startswith("static/"):
        candidate = os.path.normpath(os.path.join(_base, full_path))
        static_root = os.path.normpath(os.path.join(_base, "static")) + os.sep
        if candidate.startswith(static_root) and os.path.isfile(candidate):
            return FileResponse(candidate)
    index = os.path.join(_frontend_dir, "index.html")
    file_path = os.path.normpath(os.path.join(_frontend_dir, full_path))
    frontend_root = os.path.normpath(_frontend_dir) + os.sep
    # Serve the actual file if it exists (JS, CSS, assets, etc.) — reject anything that
    # resolves outside frontend_root (path traversal via ../ or %2e%2e%2f in full_path)
    if file_path.startswith(frontend_root) and os.path.isfile(file_path):
        return FileResponse(file_path)
    # Otherwise fall back to index.html for client-side routing
    return FileResponse(index)

if os.path.isdir(_frontend_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(_frontend_dir, "assets")), name="assets")

if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static_files")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
