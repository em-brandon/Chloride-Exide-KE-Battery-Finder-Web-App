import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import matcher
from admin_router import router as admin_router
from db import SessionLocal, engine
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from models import AdminStats
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

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
            db = SessionLocal()
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
    logger.info("Matcher caches warmed.")
    # Start the background read-counter flush timer
    threading.Timer(_READ_FLUSH_INTERVAL, _flush_read_counter).start()
    logger.info("Read counter flush timer started (every %ds).", _READ_FLUSH_INTERVAL)
    yield


app = FastAPI(title="Battery Finder API", version="1.0.0", lifespan=lifespan)

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


async def rate_limit_handler(_request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Please try again later.",
            "retry_after": exc.args[0].replace("rate limit exceeded: ", ""),
        }
    )


# ------------------------------------------------------------------
# Read counter middleware
# ------------------------------------------------------------------
@app.middleware("http")
async def count_reads_middleware(request: Request, call_next):
    """Increment the in-memory read counter for client-side GET /api/* requests only.
    Admin requests (/api/admin/*) are excluded so the counter reflects end-user traffic."""
    global _read_counter_pending
    response = await call_next(request)
    if (
        request.method == "GET"
        and request.url.path.startswith("/api/")
        and not request.url.path.startswith("/api/admin")
    ):
        with _read_counter_lock:
            _read_counter_pending += 1
    return response


# ------------------------------------------------------------------
# Request schema
# ------------------------------------------------------------------
class RecommendRequest(BaseModel):
    make: str = Field(..., json_schema_extra={"example": "TOYOTA"})
    model: str = Field(..., json_schema_extra={"example": "Corolla"})
    year: int = Field(..., ge=2000, le=2025, json_schema_extra={"example": 2015})
    engine_cc: Optional[int] = Field(None, ge=500, le=8000, json_schema_extra={"example": 1500})
    fuel_type: Optional[str] = Field(None, json_schema_extra={"example": "Petrol"})


# ------------------------------------------------------------------
# API routes
# ------------------------------------------------------------------
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
    )
    return result


# ------------------------------------------------------------------
# Serve frontend — mount last so API routes take priority
# ------------------------------------------------------------------
dist_dir = os.path.join(os.path.dirname(__file__), "frontend", "dist")
static_dir = os.path.join(os.path.dirname(__file__), "static")

if os.path.isdir(dist_dir):
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="static")
else:
    # Fallback to legacy static/ during development
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
