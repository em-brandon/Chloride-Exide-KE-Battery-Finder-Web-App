"""
Web battery validation pipeline.

Queries external sources (carapi.app → DuckDuckGo → Google Custom Search → Tavily)
to find the internet-accepted battery for each (make, model, year) combination that
does not already exist in web_battery_validation. Results are upserted into the table
so matcher.py can use them as an additional data layer.

Usage:
    python pipelines/web_battery_validate.py

Environment variables (in .env):
    DATABASE_URL             — PostgreSQL connection string (required)
    GOOGLE_SEARCH_API_KEY    — Google Custom Search API key (optional)
    GOOGLE_SEARCH_CX         — Google Programmable Search Engine ID (optional)
    GOOGLE_CSE_MONTHLY_QUOTA — override monthly Google CSE call limit (default 3000)
    TAVILY_API_KEY           — Tavily API key (optional)
    TAVILY_MONTHLY_QUOTA     — override monthly Tavily call limit (default 1000)
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
import requests
import urllib3
from dotenv import load_dotenv
from sqlalchemy import text

# ── project root on path so we can import matcher helpers ────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from matcher import _make_region, _norm_model_key, _select_batteries, _batteries

load_dotenv()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CACHE_FILE        = "cache/battery_validate_cache.json"
REQUEST_DELAY     = 0.3   # seconds between carapi calls (unlimited provider)
DDG_REQUEST_DELAY = 2.0   # DuckDuckGo per-request delay — generous to avoid silent throttle
TABLE_NAME        = "web_battery_validation"
_SEARCH_QUERY_MAX_LEN = 120

CARAPI_TRIMS_URL    = "https://carapi.app/api/trims?make={make}&model={model}&year={year}&verbose=yes&limit=50"
CARQUERY_API_URL    = "https://www.carqueryapi.com/api/0.3/"
GOOGLE_SEARCH_API_URL = "https://www.googleapis.com/customsearch/v1"

GOOGLE_SEARCH_API_KEY    = os.getenv("GOOGLE_SEARCH_API_KEY", "")
GOOGLE_SEARCH_CX         = os.getenv("GOOGLE_SEARCH_CX", "")
GOOGLE_CSE_MONTHLY_QUOTA = int(os.getenv("GOOGLE_CSE_MONTHLY_QUOTA", "3000"))
TAVILY_API_KEY           = os.getenv("TAVILY_API_KEY", "")
TAVILY_MONTHLY_QUOTA     = int(os.getenv("TAVILY_MONTHLY_QUOTA", "1000"))

_PROVIDER_DEFAULT_QUOTA: dict[str, int] = {
    "carapi":     -1,
    "duckduckgo": -1,
    "google_cse": GOOGLE_CSE_MONTHLY_QUOTA,
    "tavily":     TAVILY_MONTHLY_QUOTA,
    "carquery":   -1,
}

SESSION = requests.Session()
SESSION.verify = False
SESSION.headers["User-Agent"] = (
    "BatteryFinderBot/1.0 (chloride-exide-ke battery research; contact: admin@chloride-exide.co.ke)"
)

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def _cache_key(make_n: str, model_n: str, year: int) -> str:
    return f"{make_n}|{model_n}|{year}"


# ---------------------------------------------------------------------------
# Search query helpers
# ---------------------------------------------------------------------------

_STRIP_CHARS_RE  = re.compile(r'["\'[\]{}<>\n\r\t]')
_WHITESPACE_RE   = re.compile(r'\s+')
_DISPLACEMENT_RE = re.compile(r'\b\d+\.\d+[Ll]?\b')
_DRIVETRAIN_RE   = re.compile(r'\b(4WD|4X4|2WD|AWD|RWD)\b', re.IGNORECASE)


def _has_digit(s: str) -> bool:
    return any(c.isdigit() for c in s)


def _sanitize_search_term(s: str) -> str:
    """Strip special characters, collapse whitespace, truncate to max length."""
    s = _STRIP_CHARS_RE.sub(' ', s.strip())
    s = _WHITESPACE_RE.sub(' ', s)
    return s[:_SEARCH_QUERY_MAX_LEN].strip()


def _base_model_for_search(model: str) -> str:
    """
    Strip engine displacement, drivetrain tokens, and chassis codes from a model
    name before using it in a search query. Falls back to original if result is empty.

    Examples:
      "RANGER WILDTRAK 3.2L 4X4" → "RANGER WILDTRAK"
      "COROLLA ALTIS ZRE182L"    → "COROLLA ALTIS"
      "LAND CRUISER"             → "LAND CRUISER"
    """
    cleaned = _DISPLACEMENT_RE.sub(' ', model)
    cleaned = _DRIVETRAIN_RE.sub(' ', cleaned)
    # Strip chassis codes: all-uppercase tokens ≥6 chars that contain at least one digit
    tokens = cleaned.split()
    tokens = [t for t in tokens if not (len(t) >= 6 and t.isupper() and _has_digit(t))]
    result = ' '.join(tokens).strip()
    return result if result else model


def _build_search_query(make: str, model: str, year: int) -> str:
    base_model = _base_model_for_search(model)
    raw = f"{make} {base_model} {year} car battery AH specifications"
    return _sanitize_search_term(raw)


# ---------------------------------------------------------------------------
# Ah / technology parsers
# ---------------------------------------------------------------------------

_AH_RE  = re.compile(r"\b(\d{2,3})\s*(?:[Aa][Hh]|[Aa]mpere[- ]?[Hh]ours?)\b")
_AGM_RE = re.compile(r"\bAGM\b", re.IGNORECASE)
_EFB_RE = re.compile(r"\bEFB\b", re.IGNORECASE)
_NS_RE  = re.compile(r"\bNS\b",  re.IGNORECASE)
_DIN_RE = re.compile(r"\bDIN\b", re.IGNORECASE)


def _parse_text(raw: str) -> dict | None:
    """Extract battery specs from free text. Returns dict or None."""
    ah_hits = _AH_RE.findall(raw)
    if not ah_hits:
        return None

    ah = int(max(set(ah_hits), key=ah_hits.count))

    tech = "MF"
    if _AGM_RE.search(raw):
        tech = "AGM"
    elif _EFB_RE.search(raw):
        tech = "EFB"

    region = None
    if _NS_RE.search(raw):
        region = "NS"
    elif _DIN_RE.search(raw):
        region = "DIN"

    return {"ah": ah, "technology": tech, "region": region}


# ---------------------------------------------------------------------------
# Provider lookups
# ---------------------------------------------------------------------------

def _carapi_lookup(make: str, model: str, year: int) -> dict | None:
    """Query carapi.app trims endpoint; return parsed battery dict or None."""
    url = CARAPI_TRIMS_URL.format(
        make=requests.utils.quote(make.title()),
        model=requests.utils.quote(model.title()),
        year=year,
    )
    for attempt in range(3):
        try:
            resp = SESSION.get(url, timeout=15)
            if resp.status_code == 429:
                wait = 15 * (attempt + 1)
                print(f"    [CARAPI] 429 — waiting {wait}s")
                time.sleep(wait)
                continue
            if not resp.ok:
                return None
            trims = resp.json().get("data", [])
            if not trims:
                return None
            full_text = " ".join(
                str(t.get("description", "")) + " " + str(t.get("specs", ""))
                for t in trims
            )
            return _parse_text(full_text) if full_text.strip() else None
        except Exception:
            return None
    return None


def _carquery_lookup(make: str, model: str, year: int) -> dict | None:
    """
    Query carquery.com for engine CC and fuel type (vehicle spec enrichment only —
    not a battery source). Returns {"engine_cc": int, "fuel": str} or None.
    """
    params = {
        "cmd":        "getTrims",
        "make":       make.title(),
        "model":      model.title(),
        "year":       year,
        "sold_in_us": 0,
    }
    for attempt in range(3):
        try:
            resp = SESSION.get(CARQUERY_API_URL, params=params, timeout=15)
            if resp.status_code == 429:
                time.sleep(15 * (attempt + 1))
                continue
            if not resp.ok:
                return None
            trims = resp.json().get("Trims", [])
            for trim in trims:
                raw_cc = trim.get("model_engine_cc") or trim.get("model_engine_position_cc")
                try:
                    cc_int = int(raw_cc)
                except (TypeError, ValueError):
                    cc_int = 0
                if cc_int > 0:
                    fuel = (trim.get("model_fuel_type") or "").strip()
                    return {"engine_cc": cc_int, "fuel": fuel}
            return None
        except Exception:
            return None
    return None


def _duckduckgo_lookup(make: str, model: str, year: int) -> dict | None:
    """Query DuckDuckGo and parse battery Ah from snippets. Returns dict or None."""
    from ddgs import DDGS
    queries = [
        _build_search_query(make, model, year),
        _sanitize_search_term(f"{make} {_base_model_for_search(model)} battery capacity ampere hours"),
        _sanitize_search_term(f"{make} {_base_model_for_search(model)} 12V battery technical specifications"),
    ]
    for attempt in range(3):
        try:
            ddgs = DDGS()
            for query in queries:
                results = list(ddgs.text(query, max_results=5))
                if not results:
                    # Empty results = silent throttle — back off before next query
                    time.sleep(DDG_REQUEST_DELAY)
                    continue
                combined = " ".join(
                    (r.get("title", "") + " " + r.get("body", "")) for r in results
                )
                parsed = _parse_text(combined)
                if parsed:
                    return parsed
                time.sleep(DDG_REQUEST_DELAY)
            return None
        except Exception as exc:
            err = str(exc).lower()
            if any(k in err for k in ("ratelimit", "429", "rate limit", "too many")):
                wait = 30 * (attempt + 1)
                print(f"    [DDG] rate-limited — waiting {wait}s")
                time.sleep(wait)
                continue
            return None
    return None


def _google_cse_lookup(make: str, model: str, year: int) -> dict | None:
    """Query Google Custom Search and parse battery Ah. Returns dict or None."""
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_SEARCH_CX:
        return None
    query = _build_search_query(make, model, year)
    params = {"key": GOOGLE_SEARCH_API_KEY, "cx": GOOGLE_SEARCH_CX, "q": query, "num": 5}
    for attempt in range(3):
        try:
            resp = SESSION.get(GOOGLE_SEARCH_API_URL, params=params, timeout=15)
            if resp.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"    [GOOGLE] 429 — waiting {wait}s")
                time.sleep(wait)
                continue
            if not resp.ok:
                return None
            items = resp.json().get("items", [])
            combined = " ".join(
                (i.get("title", "") + " " + i.get("snippet", "")) for i in items
            )
            return _parse_text(combined) if combined.strip() else None
        except Exception:
            return None
    return None


def _tavily_lookup(make: str, model: str, year: int) -> dict | None:
    """Query Tavily AI search and parse battery Ah. Returns dict or None."""
    if not TAVILY_API_KEY:
        return None
    query = _build_search_query(make, model, year)
    try:
        from tavily import TavilyClient
        results = TavilyClient(api_key=TAVILY_API_KEY).search(query, max_results=5)
        combined = " ".join(r.get("content", "") for r in results.get("results", []))
        return _parse_text(combined) if combined.strip() else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Quota helpers (raw SQL — works in both CLI and background thread contexts)
# ---------------------------------------------------------------------------

def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _ensure_quota_row(eng, provider: str, month: str) -> None:
    quota_limit = _PROVIDER_DEFAULT_QUOTA.get(provider, -1)
    now = datetime.now(timezone.utc)
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO api_usage_quota (provider, month, calls_made, quota_limit, updated_at)
            VALUES (:provider, :month, 0, :quota_limit, :now)
            ON CONFLICT (provider, month) DO NOTHING
        """), {"provider": provider, "month": month, "quota_limit": quota_limit, "now": now})


def _check_quota(eng, provider: str, month: str) -> bool:
    """Return True if the provider has remaining quota (or is unlimited).
    Returns False immediately for providers whose API keys are not configured —
    this prevents phantom quota rows being created for unconfigured services.
    """
    if provider == "google_cse" and not (GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX):
        return False
    if provider == "tavily" and not TAVILY_API_KEY:
        return False
    _ensure_quota_row(eng, provider, month)
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT calls_made, quota_limit FROM api_usage_quota WHERE provider=:p AND month=:m"
        ), {"p": provider, "m": month}).fetchone()
    if row is None:
        return True
    calls_made, quota_limit = row
    return quota_limit == -1 or calls_made < quota_limit


def _increment_quota(eng, provider: str, month: str) -> None:
    now = datetime.now(timezone.utc)
    with eng.begin() as conn:
        conn.execute(text("""
            UPDATE api_usage_quota
            SET calls_made = calls_made + 1, updated_at = :now
            WHERE provider = :p AND month = :m
        """), {"p": provider, "m": month, "now": now})


# ---------------------------------------------------------------------------
# Resolve parsed specs to a battery_code from battery_specs
# ---------------------------------------------------------------------------

def _resolve_battery_code(parsed: dict, make_n: str) -> tuple[str, int, str] | None:
    region = parsed.get("region") or _make_region(make_n)
    ah     = parsed["ah"]
    tech   = parsed["technology"]
    try:
        primary, _ = _select_batteries(ah, tech, region)
        return primary["battery_code"], ah, tech
    except Exception:
        return None


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

def _upsert_rows(eng, rows: list[dict], run_id: str | None = None) -> None:
    if not rows:
        return
    now = datetime.now(timezone.utc)
    with eng.begin() as conn:
        for row in rows:
            conn.execute(
                text(f"""
                    INSERT INTO {TABLE_NAME}
                        (make_n, model_n, year, battery_code, ah, technology,
                         source, engine_cc, fuel_type, validated_at, run_id)
                    VALUES
                        (:make_n, :model_n, :year, :battery_code, :ah, :technology,
                         :source, :engine_cc, :fuel_type, :validated_at, :run_id)
                    ON CONFLICT (make_n, model_n, year)
                    DO UPDATE SET
                        battery_code = EXCLUDED.battery_code,
                        ah           = EXCLUDED.ah,
                        technology   = EXCLUDED.technology,
                        source       = EXCLUDED.source,
                        engine_cc    = EXCLUDED.engine_cc,
                        fuel_type    = EXCLUDED.fuel_type,
                        validated_at = EXCLUDED.validated_at,
                        run_id       = EXCLUDED.run_id
                """),
                {**row, "validated_at": now, "run_id": run_id},
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
    progress_callback: Callable | None = None,  # (processed, total, provider)
    log_callback: Callable | None = None,        # (line: str)
    enabled_providers: list[str] | None = None,  # None = all available providers
    run_id: str | None = None,                   # UUID from admin_router — tags DB rows
) -> dict:
    """
    Run the web battery validation pipeline.

    Returns {"fetched": int, "cached": int, "failed": int, "provider_counts": dict}.
    """
    from db import engine

    def _log(line: str) -> None:
        print(line)
        if log_callback:
            log_callback(line)

    _log("[START] web_battery_validate.py")
    month = _current_month()

    # Which providers are active for this run
    _ep = set(enabled_providers) if enabled_providers is not None else None

    def _is_enabled(p: str) -> bool:
        return _ep is None or p in _ep

    if _ep is not None:
        _log(f"  [CONFIG] enabled providers: {', '.join(sorted(_ep))}")

    # Load all (make, model, year, engine_capacity, fuel) from vehicle_years
    veh = pd.read_sql(
        "SELECT UPPER(TRIM(make)) AS make_n,"
        " model AS raw_model, year,"
        " engine_capacity, fuel"
        " FROM vehicle_years"
        " WHERE year IS NOT NULL",
        engine,
    )
    veh["model_n"] = veh["raw_model"].astype(str).apply(_norm_model_key)
    veh["year"]    = pd.to_numeric(veh["year"], errors="coerce").astype("Int64")
    veh = veh.dropna(subset=["make_n", "model_n", "year"])

    # Group to unique combos; take first non-null engine/fuel per (make, model, year)
    combos = (
        veh.groupby(["make_n", "model_n", "year"], as_index=False)
        .agg({"engine_capacity": "first", "fuel": "first"})
    )
    combos["year"] = combos["year"].astype(int)
    _log(f"  {len(combos)} unique (make, model, year) combinations in vehicle_years")

    # Load already-validated combos
    try:
        existing = pd.read_sql(
            f"SELECT make_n, model_n, year FROM {TABLE_NAME}", engine
        )
        existing["year"] = pd.to_numeric(existing["year"], errors="coerce").astype(int)
        existing_keys = set(zip(existing["make_n"], existing["model_n"], existing["year"]))
    except Exception:
        existing_keys = set()
    _log(f"  {len(existing_keys)} already validated — skipping")

    cache = _load_cache()
    new_rows: list[dict] = []
    n_cached = n_fetched = n_failed = 0
    provider_counts: dict[str, int] = {
        "carapi": 0, "duckduckgo": 0, "google_cse": 0, "tavily": 0,
    }
    # Web-search providers (DDG / Google / Tavily) return the same results regardless of
    # model year. Cache the result keyed by make+model so we only call them once per model
    # instead of once per make/model/year — reduces 60k calls to ~3.3k.
    _model_web_cache: dict[str, dict | None] = {}  # "MAKE|MODEL" → parsed or None (miss)
    total = len(combos) - len(existing_keys)

    for _, row in combos.iterrows():
        if cancel_event and cancel_event.is_set():
            _log("  [CANCELLED] pipeline stopped by user")
            break

        # Pause: block until resumed or cancelled
        if pause_event and pause_event.is_set():
            _log("  [PAUSED] waiting for resume…")
            while pause_event.is_set():
                if cancel_event and cancel_event.is_set():
                    break
                time.sleep(0.5)
            if cancel_event and cancel_event.is_set():
                _log("  [CANCELLED] pipeline stopped while paused")
                break

        make_n  = str(row["make_n"])
        model_n = str(row["model_n"])
        year    = int(row["year"])
        key     = _cache_key(make_n, model_n, year)

        # engine_cc and fuel_type come from vehicle_years — never from any API
        raw_cc   = row["engine_capacity"]
        raw_fuel = row["fuel"]
        engine_cc = int(raw_cc)   if pd.notna(raw_cc)   else None
        fuel_type = str(raw_fuel) if pd.notna(raw_fuel) else None

        if (make_n, model_n, year) in existing_keys:
            continue

        # Check file cache first
        if key in cache:
            cached = cache[key]
            if cached is not None:
                new_rows.append(cached)
            n_cached += 1
            if progress_callback:
                progress_callback(n_cached + n_fetched + n_failed, total, "cache")
            continue

        _log(f"  [FETCH] {make_n} {model_n} {year}")
        parsed: dict | None = None
        source_provider = "none"

        # ── carquery.com: enrich engine_cc when missing from vehicle_years ──────
        if not engine_cc and _check_quota(engine, "carquery", month):
            cq = _carquery_lookup(make_n, model_n, year)
            _increment_quota(engine, "carquery", month)
            if cq:
                engine_cc = cq.get("engine_cc")
                if not fuel_type:
                    fuel_type = cq.get("fuel")
                _log(f"    [CARQUERY] engine_cc={engine_cc} fuel={fuel_type}")
            time.sleep(REQUEST_DELAY)

        # ── carapi.app ────────────────────────────────────────────────────────────
        if _is_enabled("carapi") and _check_quota(engine, "carapi", month):
            parsed = _carapi_lookup(make_n, model_n, year)
            _increment_quota(engine, "carapi", month)
            if parsed:
                source_provider = "carapi"
                provider_counts["carapi"] += 1
                _log(f"    [CARAPI] Ah={parsed['ah']} tech={parsed['technology']}")
            time.sleep(REQUEST_DELAY)

        # ── Web search providers (DDG → Google CSE → Tavily) ─────────────────────
        # These are called at most once per make+model (not per year) because the
        # results are virtually identical across model years. The cache is keyed by
        # "MAKE|MODEL" and persists for the lifetime of this run.
        if parsed is None:
            web_cache_key = f"{make_n}|{model_n}"
            if web_cache_key in _model_web_cache:
                # Reuse result from a previous year of the same model — no API call needed
                web_hit = _model_web_cache[web_cache_key]
                if web_hit:
                    parsed = web_hit
                    source_provider = "web_cached"
                    _log(f"    [WEB-CACHE] Ah={parsed['ah']} tech={parsed['technology']}")
            else:
                web_parsed: dict | None = None

                if web_parsed is None and _is_enabled("duckduckgo") and _check_quota(engine, "duckduckgo", month):
                    web_parsed = _duckduckgo_lookup(make_n, model_n, year)
                    _increment_quota(engine, "duckduckgo", month)
                    if web_parsed:
                        source_provider = "duckduckgo"
                        provider_counts["duckduckgo"] += 1
                        _log(f"    [DDG] Ah={web_parsed['ah']} tech={web_parsed['technology']}")
                    time.sleep(DDG_REQUEST_DELAY)

                if web_parsed is None and _is_enabled("google_cse") and _check_quota(engine, "google_cse", month):
                    web_parsed = _google_cse_lookup(make_n, model_n, year)
                    _increment_quota(engine, "google_cse", month)
                    if web_parsed:
                        source_provider = "google_cse"
                        provider_counts["google_cse"] += 1
                        _log(f"    [GOOGLE] Ah={web_parsed['ah']} tech={web_parsed['technology']}")
                    time.sleep(REQUEST_DELAY)

                if web_parsed is None and _is_enabled("tavily") and _check_quota(engine, "tavily", month):
                    web_parsed = _tavily_lookup(make_n, model_n, year)
                    _increment_quota(engine, "tavily", month)
                    if web_parsed:
                        source_provider = "tavily"
                        provider_counts["tavily"] += 1
                        _log(f"    [TAVILY] Ah={web_parsed['ah']} tech={web_parsed['technology']}")
                    time.sleep(REQUEST_DELAY)

                _model_web_cache[web_cache_key] = web_parsed
                parsed = web_parsed

        if parsed is None:
            _log(f"    [SKIP] no result from any provider")
            cache[key] = None
            n_failed += 1
            _save_cache(cache)
            if progress_callback:
                progress_callback(n_cached + n_fetched + n_failed, total, "none")
            continue

        resolved = _resolve_battery_code(parsed, make_n)
        if resolved is None:
            _log(f"    [SKIP] could not resolve to battery_code")
            cache[key] = None
            n_failed += 1
            _save_cache(cache)
            if progress_callback:
                progress_callback(n_cached + n_fetched + n_failed, total, "none")
            continue

        battery_code, ah, technology = resolved
        db_row = {
            "make_n":       make_n,
            "model_n":      model_n,
            "year":         year,
            "battery_code": battery_code,
            "ah":           ah,
            "technology":   technology,
            "source":       source_provider,
            "engine_cc":    engine_cc,
            "fuel_type":    fuel_type,
        }
        cache[key] = db_row
        new_rows.append(db_row)
        n_fetched += 1
        _save_cache(cache)

        if progress_callback:
            progress_callback(n_cached + n_fetched + n_failed, total, source_provider)

        # Flush every 50 rows to avoid losing progress
        if len(new_rows) >= 50:
            _upsert_rows(engine, new_rows, run_id=run_id)
            new_rows = []

    # Final flush
    _upsert_rows(engine, new_rows, run_id=run_id)

    # Determine whether pipeline finished normally or was cancelled
    was_cancelled = bool(cancel_event and cancel_event.is_set())
    run_status = "cancelled" if was_cancelled else "completed"

    # Log to pipeline_run_log for staleness tracking
    if run_id:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO pipeline_run_log (run_id, status, combos_processed, combos_matched)"
                        " VALUES (:run_id, :status, :processed, :matched)"
                    ),
                    {
                        "run_id":    run_id,
                        "status":    run_status,
                        "processed": n_cached + n_fetched + n_failed,
                        "matched":   n_fetched + n_cached,
                    },
                )
        except Exception as exc:
            _log(f"  [WARN] could not write pipeline_run_log: {exc}")

    _log(
        f"\n[END] Done — {n_fetched} fetched, {n_cached} from cache, {n_failed} no result"
    )
    return {
        "fetched":         n_fetched,
        "cached":          n_cached,
        "failed":          n_failed,
        "provider_counts": provider_counts,
    }


if __name__ == "__main__":
    main()
