import os
from typing import Optional

import matcher
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

app = FastAPI(title="Battery Finder API", version="1.0.0")

# ------------------------------------------------------------------
# Rate limiting setup
# ------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

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
# Request schema
# ------------------------------------------------------------------
class RecommendRequest(BaseModel):
    make: str = Field(..., json_schema_extra={"example": "TOYOTA"})
    model: str = Field(..., json_schema_extra={"example": "Corolla"})
    year: int = Field(..., ge=2000, le=2025, json_schema_extra={"example": 2015})
    engine_cc: Optional[int] = Field(None, ge=500, le=8000, json_schema_extra={"example": 1500})
    fuel_type: Optional[str] = Field(None, json_schema_extra={"example": "Petrol"})
    has_stop_start: bool = Field(False, json_schema_extra={"example": False})


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
        req.has_stop_start,
    )
    return result


# ------------------------------------------------------------------
# Serve frontend — mount last so API routes take priority
# ------------------------------------------------------------------
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
