"""
Web battery validation pipeline.

Queries external sources (SearXNG → DuckDuckGo → Brave → Tavily)
to find the internet-accepted battery for each (make, model, year) combination that
does not already exist in web_battery_validation. Results are upserted into the table
so matcher.py can use them as an additional data layer.

Usage:
    python pipelines/web_battery_validate.py

Environment variables (in .env):
    DATABASE_URL             — PostgreSQL connection string (required)
    SEARXNG_URL              — SearXNG base URL e.g. http://localhost:8888 (optional; skipped if unset)
    BRAVE_SEARCH_API_KEY     — Brave Search API key (optional)
    BRAVE_MONTHLY_QUOTA      — override monthly Brave call limit (default 2000)
    TAVILY_API_KEY           — Tavily API key (optional)
    TAVILY_MONTHLY_QUOTA     — override monthly Tavily call limit (default 1000)
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
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

CACHE_FILE           = "cache/battery_validate_cache.json"
WEB_MODEL_CACHE_FILE = "cache/web_model_cache.json"
REQUEST_DELAY        = 0.3   # seconds between provider calls
DDG_REQUEST_DELAY    = 0.5   # DuckDuckGo per-request delay
MAX_WORKERS           = int(os.getenv("VALIDATE_MAX_WORKERS",      "15"))  # Phase 2 workers
WEB_PREFETCH_WORKERS  = int(os.getenv("VALIDATE_WEB_WORKERS",     "3"))   # Phase 1 DDG/web workers
CACHE_SAVE_INTERVAL   = int(os.getenv("VALIDATE_CACHE_INTERVAL",  "100")) # save cache every N rows
WEB_MODEL_SAVE_INTERVAL = 20  # persist web model cache every N fetched models
TABLE_NAME        = "web_battery_validation"
_SEARCH_QUERY_MAX_LEN = 120

CARQUERY_API_URL    = "https://www.carqueryapi.com/api/0.3/"

TAVILY_API_KEY           = os.getenv("TAVILY_API_KEY", "")
TAVILY_MONTHLY_QUOTA     = int(os.getenv("TAVILY_MONTHLY_QUOTA", "1000"))
BRAVE_SEARCH_API_KEY     = os.getenv("BRAVE_SEARCH_API_KEY", "")
BRAVE_MONTHLY_QUOTA      = int(os.getenv("BRAVE_MONTHLY_QUOTA", "2000"))
BRAVE_SEARCH_API_URL     = "https://api.search.brave.com/res/v1/web/search"
SEARXNG_URL              = os.getenv("SEARXNG_URL", "")   # empty = disabled

_PROVIDER_DEFAULT_QUOTA: dict[str, int] = {
    "duckduckgo": -1,
    "searxng":    -1,
    "brave":      BRAVE_MONTHLY_QUOTA,
    "tavily":     TAVILY_MONTHLY_QUOTA,
    "carquery":   -1,
}

SESSION = requests.Session()
SESSION.verify = False
SESSION.headers["User-Agent"] = (
    "BatteryFinderBot/1.0 (chloride-exide-ke battery research; contact: admin@chloride-exide.co.ke)"
)

# Network-outage detection state (set = network is OK; cleared = outage detected)
_net_ok_event   = threading.Event()
_net_ok_event.set()
_net_check_lock = threading.Lock()  # ensures only one thread polls connectivity

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


def _load_web_model_cache() -> dict:
    if os.path.exists(WEB_MODEL_CACHE_FILE):
        try:
            with open(WEB_MODEL_CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_web_model_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(WEB_MODEL_CACHE_FILE), exist_ok=True)
    with open(WEB_MODEL_CACHE_FILE, "w") as f:
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


def _build_query(make: str, model: str, tail: str) -> str:
    """
    Build a search query, truncating only the trim-name portion when the
    full string would exceed _SEARCH_QUERY_MAX_LEN — never the trailing
    `tail` (year + keyword suffix). A few real trim names (option-list-laden
    Toyota/Jeep model strings) are long enough that naively truncating the
    assembled string cuts into "car battery AH specifications" itself,
    chopping the very keywords that signal battery-spec intent to the
    search engine.
    """
    make = _sanitize_search_term(make)
    base_model = _sanitize_search_term(_base_model_for_search(model))
    budget = _SEARCH_QUERY_MAX_LEN - len(make) - len(tail) - 2  # 2 separating spaces
    if budget < len(base_model):
        base_model = base_model[:max(budget, 0)].strip()
    return f"{make} {base_model} {tail}".strip()


def _build_search_query(make: str, model: str, year: int) -> str:
    return _build_query(make, model, f"{year} car battery AH specifications")


# ---------------------------------------------------------------------------
# Ah / technology parsers
# ---------------------------------------------------------------------------

_AH_RE      = re.compile(r"\b(\d{2,3})\s*(?:[Aa][Hh]|[Aa]mpere[- ]?[Hh]ours?)\b")
_AGM_RE     = re.compile(r"\bAGM\b", re.IGNORECASE)
_EFB_RE     = re.compile(r"\bEFB\b", re.IGNORECASE)
_NS_RE      = re.compile(r"\bNS\b",  re.IGNORECASE)
_DIN_RE     = re.compile(r"\bDIN\b", re.IGNORECASE)
_LITHIUM_RE = re.compile(r"\b(lithium|lifepo4|li-?ion)\b", re.IGNORECASE)


def _parse_snippets(snippets: list[str]) -> dict | None:
    """
    Extract battery specs from an ordered list of search-result snippets
    (title + description/body per result, in the relevance order the
    provider returned them).

    An Ah figure is scored by how many *distinct* results mention it, not
    by raw regex-hit count in one combined blob — otherwise a single wordy
    result repeating a number outweighs two independent results that
    agree. Snippets describing lithium/LiFePO4 batteries are skipped
    entirely: their Ah ratings use a different capacity convention than
    the lead-acid MF/AGM/EFB catalog this app matches against, so mixing
    them in would silently corrupt the vote. Ties are broken by preferring
    the value seen in the highest-ranked (earliest) result, which is
    deterministic — unlike relying on Python's set-iteration order.
    """
    votes: dict[int, int] = {}
    first_rank: dict[int, int] = {}
    has_agm = has_efb = has_ns = has_din = False

    for rank, snippet in enumerate(snippets):
        if not snippet or not snippet.strip() or _LITHIUM_RE.search(snippet):
            continue
        for ah in set(int(m) for m in _AH_RE.findall(snippet)):
            votes[ah] = votes.get(ah, 0) + 1
            first_rank.setdefault(ah, rank)
        has_agm = has_agm or bool(_AGM_RE.search(snippet))
        has_efb = has_efb or bool(_EFB_RE.search(snippet))
        has_ns  = has_ns  or bool(_NS_RE.search(snippet))
        has_din = has_din or bool(_DIN_RE.search(snippet))

    if not votes:
        return None

    ah = max(votes, key=lambda a: (votes[a], -first_rank[a]))
    tech = "AGM" if has_agm else "EFB" if has_efb else "MF"
    region = "NS" if has_ns else "DIN" if has_din else None

    return {"ah": ah, "technology": tech, "region": region}


# ---------------------------------------------------------------------------
# Interruptible sleep helper
# ---------------------------------------------------------------------------

def _interruptible_sleep(secs: float, cancel_event: threading.Event | None = None) -> None:
    """Sleep for `secs` seconds, waking early if cancel_event is set (checks every 0.5 s)."""
    deadline = time.monotonic() + secs
    while time.monotonic() < deadline:
        if cancel_event and cancel_event.is_set():
            return
        time.sleep(min(0.5, deadline - time.monotonic()))


# ---------------------------------------------------------------------------
# Provider lookups
# ---------------------------------------------------------------------------


def _carquery_lookup(make: str, model: str, year: int, cancel_event: threading.Event | None = None) -> dict | None:
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
                _interruptible_sleep(15 * (attempt + 1), cancel_event)
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


def _duckduckgo_lookup(make: str, model: str, year: int, cancel_event: threading.Event | None = None) -> dict | None:
    """Query DuckDuckGo and parse battery Ah from snippets. Returns dict or None."""
    from ddgs import DDGS
    queries = [
        _build_search_query(make, model, year),
        _build_query(make, model, "battery capacity ampere hours"),
        _build_query(make, model, "12V battery technical specifications"),
    ]
    for attempt in range(3):
        try:
            ddgs = DDGS(timeout=10)
            for query in queries:
                results = list(ddgs.text(query, max_results=5))
                if not results:
                    # Empty results = silent throttle — back off before next query
                    _interruptible_sleep(DDG_REQUEST_DELAY, cancel_event)
                    continue
                snippets = [r.get("title", "") + " " + r.get("body", "") for r in results]
                parsed = _parse_snippets(snippets)
                if parsed:
                    return parsed
                _interruptible_sleep(DDG_REQUEST_DELAY, cancel_event)
            return None
        except Exception as exc:
            err = str(exc).lower()
            if any(k in err for k in ("ratelimit", "429", "rate limit", "too many")):
                wait = 30 * (attempt + 1)
                print(f"    [DDG] rate-limited — waiting {wait}s")
                _interruptible_sleep(wait, cancel_event)
                continue
            if any(k in err for k in (
                "network is unreachable", "failed to establish a new connection",
                "no route to host", "name or service not known",
                "temporary failure in name resolution",
            )):
                raise
            return None
    return None


def _searxng_lookup(make: str, model: str, year: int, cancel_event: threading.Event | None = None) -> dict | None:
    """Query local SearXNG instance and parse battery Ah. Returns dict or None."""
    if not SEARXNG_URL:
        return None
    query = _build_search_query(make, model, year)
    try:
        resp = SESSION.get(
            f"{SEARXNG_URL.rstrip('/')}/search",
            params={"q": query, "format": "json", "categories": "general"},
            timeout=15,
        )
        if not resp.ok:
            return None
        results = resp.json().get("results", [])[:5]
        snippets = [r.get("title", "") + " " + r.get("content", "") for r in results]
        return _parse_snippets(snippets)
    except Exception as exc:
        err = str(exc).lower()
        if any(k in err for k in (
            "network is unreachable", "failed to establish a new connection",
            "no route to host", "name or service not known",
            "temporary failure in name resolution",
        )):
            raise
        return None


def _brave_lookup(make: str, model: str, year: int, cancel_event: threading.Event | None = None) -> dict | None:
    """Query Brave Search API and parse battery Ah. Returns dict or None."""
    if not BRAVE_SEARCH_API_KEY:
        return None
    query = _build_search_query(make, model, year)
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
    }
    for attempt in range(3):
        try:
            resp = SESSION.get(
                BRAVE_SEARCH_API_URL,
                params={"q": query, "count": 20},
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"    [BRAVE] 429 — waiting {wait}s")
                _interruptible_sleep(wait, cancel_event)
                continue
            if not resp.ok:
                return None
            results = resp.json().get("web", {}).get("results", [])
            snippets = [r.get("title", "") + " " + r.get("description", "") for r in results]
            return _parse_snippets(snippets)
        except Exception as exc:
            err = str(exc).lower()
            if any(k in err for k in (
                "network is unreachable", "failed to establish a new connection",
                "no route to host", "name or service not known",
                "temporary failure in name resolution",
            )):
                raise
            return None
    return None


def _tavily_lookup(make: str, model: str, year: int, cancel_event: threading.Event | None = None) -> dict | None:
    """Query Tavily AI search and parse battery Ah. Returns dict or None."""
    if not TAVILY_API_KEY:
        return None
    query = _build_search_query(make, model, year)
    try:
        from tavily import TavilyClient
        results = TavilyClient(api_key=TAVILY_API_KEY).search(query, max_results=5)
        snippets = [r.get("content", "") for r in results.get("results", [])]
        return _parse_snippets(snippets)
    except Exception as exc:
        err = str(exc).lower()
        if any(k in err for k in (
            "network is unreachable", "failed to establish a new connection",
            "no route to host", "name or service not known",
            "temporary failure in name resolution", "broken pipe", "reset by peer",
        )):
            raise
        return None


# ---------------------------------------------------------------------------
# Quota helpers (raw SQL — works in both CLI and background thread contexts)
# ---------------------------------------------------------------------------

def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


_ONE_TIME_QUOTA_PROVIDERS = {"brave"}  # prepaid credit balance — never auto-resets


def _ensure_quota_row(eng, provider: str) -> None:
    """
    Create an active quota row for *provider* if none exists.

    Most providers (tavily, etc.) get a rolling 30-day window matching their
    recurring monthly free-tier allowance. Providers in _ONE_TIME_QUOTA_PROVIDERS
    (brave) instead get period_end=NULL — a single quota row that accumulates
    calls_made forever and never resets, since brave is billed against a
    prepaid credit balance rather than a monthly free quota; once quota_limit
    is hit it stays hit until someone raises it after topping up credit.
    """
    quota_limit = _PROVIDER_DEFAULT_QUOTA.get(provider, -1)
    now = datetime.now(timezone.utc)
    month = now.strftime("%Y-%m")
    period_end = None if provider in _ONE_TIME_QUOTA_PROVIDERS else now + timedelta(days=30)
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO api_usage_quota
                (provider, month, calls_made, quota_limit, updated_at, period_start, period_end)
            VALUES
                (:provider, :month, 0, :quota_limit, :now, :period_start, :period_end)
            ON CONFLICT (provider, month) DO NOTHING
        """), {
            "provider": provider, "month": month, "quota_limit": quota_limit,
            "now": now, "period_start": now, "period_end": period_end,
        })


def _check_quota(eng, provider: str) -> bool:
    """Return True if the provider has remaining quota (or is unlimited).
    Returns False immediately for providers whose API keys are not configured —
    this prevents phantom quota rows being created for unconfigured services.
    Automatically starts a new 30-day period if the previous one has expired.
    """
    if provider == "brave" and not BRAVE_SEARCH_API_KEY:
        return False
    if provider == "searxng" and not SEARXNG_URL:
        return False
    if provider == "tavily" and not TAVILY_API_KEY:
        return False

    now = datetime.now(timezone.utc)
    with eng.connect() as conn:
        row = conn.execute(text("""
            SELECT calls_made, quota_limit FROM api_usage_quota
            WHERE provider = :p AND (period_end IS NULL OR period_end > :now)
            ORDER BY period_start DESC NULLS LAST LIMIT 1
        """), {"p": provider, "now": now}).fetchone()

    if row is None:
        # No active period — create one and allow the call
        _ensure_quota_row(eng, provider)
        return True

    calls_made, quota_limit = row
    return quota_limit == -1 or calls_made < quota_limit


def _increment_quota(eng, provider: str) -> None:
    now = datetime.now(timezone.utc)
    with eng.begin() as conn:
        conn.execute(text("""
            UPDATE api_usage_quota
            SET calls_made = calls_made + 1, updated_at = :now
            WHERE provider = :p
              AND (period_end IS NULL OR period_end > :now)
        """), {"p": provider, "now": now})


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
    progress_callback: Callable | None = None,         # (processed, total, provider)
    log_callback: Callable | None = None,              # (line: str)
    enabled_providers: list[str] | None = None,        # None = all available providers
    enabled_makes: list[str] | None = None,             # None = all makes; [] = zero makes
    run_id: str | None = None,                         # UUID from admin_router — tags DB rows
    phase1_progress_callback: Callable | None = None,  # (fetched, total)
    phase: str = "both",                               # "phase1", "phase2", or "both"
) -> dict:
    """
    Run the web battery validation pipeline.

    Two-phase concurrent execution:
      Phase 1 — pre-fetch web results (DDG/Google/Tavily) for all unique (make, model)
                 pairs using WEB_PREFETCH_WORKERS threads (default 2).  Results are
                 stored in _model_web_cache so Phase 2 workers never call web APIs.
      Phase 2 — process every (make, model, year) combo with MAX_WORKERS threads
                 (default 15).  Each worker reads the pre-fetched web cache keyed
                 by 5-year generation bucket and writes to the DB.

    Returns {"fetched": int, "cached": int, "failed": int, "provider_counts": dict}.
    """
    from concurrent.futures import ThreadPoolExecutor
    from db import engine

    def _log(line: str) -> None:
        print(line)
        if log_callback:
            log_callback(line)

    def _is_cancelled() -> bool:
        return bool(cancel_event and cancel_event.is_set())

    def _wait_if_paused() -> bool:
        """Block while paused. Returns False if pipeline was cancelled."""
        if pause_event and pause_event.is_set():
            while pause_event and pause_event.is_set():
                if _is_cancelled():
                    return False
                time.sleep(0.5)
        return not _is_cancelled()

    def _is_net_error(exc: Exception) -> bool:
        s = str(exc).lower()
        return any(k in s for k in (
            "network is unreachable",
            "failed to establish a new connection",
            "no route to host",
            "name or service not known",
            "nodename nor servname provided",
            "temporary failure in name resolution",
        ))

    def _wait_for_net() -> bool:
        """
        Block until network is restored or 3 minutes have elapsed.
        Returns True if network came back, False if timed out or cancelled.
        Only one thread polls; others just wait for _net_ok_event.
        """
        if _net_ok_event.is_set():
            return True
        if _net_check_lock.acquire(blocking=False):
            try:
                if _net_ok_event.is_set():
                    return True
                # Immediate check — handles transient DNS hiccups without any wait
                try:
                    socket.create_connection(("8.8.8.8", 53), timeout=5).close()
                    _net_ok_event.set()
                    return True   # transient error, unblock workers silently
                except OSError:
                    pass          # genuine outage — enter polling loop
                _log("  [NET] Connection lost — pausing up to 3 min waiting for reconnect…")
                for attempt in range(6):  # 6 × 30 s = 3 minutes
                    _interruptible_sleep(30, cancel_event)
                    if _is_cancelled():
                        break
                    try:
                        socket.create_connection(("8.8.8.8", 53), timeout=5).close()
                        _net_ok_event.set()
                        _log("  [NET] Connection restored — resuming pipeline")
                        return True
                    except OSError:
                        _log(f"  [NET] Still no connection ({attempt + 1}/6)…")
                # Timed out (or cancelled) — save cache and stop
                _log("  [NET] No connection after 3 min — saving cache and stopping pipeline")
                with _cache_lock:
                    _save_web_model_cache(_model_web_cache)
                if cancel_event:
                    cancel_event.set()
                _net_ok_event.set()  # unblock any waiting workers
                return False
            finally:
                _net_check_lock.release()
        else:
            # Another thread is already polling — just wait
            while not _is_cancelled() and not _net_ok_event.is_set():
                time.sleep(1)
            return not _is_cancelled()

    _net_ok_event.set()  # reset network state at start of each run

    _log("[START] web_battery_validate.py")

    _ep = set(enabled_providers) if enabled_providers is not None else None

    def _is_enabled(p: str) -> bool:
        return _ep is None or p in _ep

    if _ep is not None:
        _log(f"  [CONFIG] enabled providers: {', '.join(sorted(_ep))}")

    # Pre-seed quota rows for all providers
    for _p in ["duckduckgo", "searxng", "brave", "tavily", "carquery"]:
        _ensure_quota_row(engine, _p)

    # Log which providers will actually be used this run
    for _pn in ["duckduckgo", "searxng", "brave", "tavily"]:
        if not _is_enabled(_pn):
            continue
        if _pn == "searxng" and not SEARXNG_URL:
            _log(f"  [CONFIG] {_pn}: SEARXNG_URL not set — will be skipped")
        elif _pn == "brave" and not BRAVE_SEARCH_API_KEY:
            _log(f"  [CONFIG] {_pn}: no API key — will be skipped")
        elif _pn == "tavily" and not TAVILY_API_KEY:
            _log(f"  [CONFIG] {_pn}: no API key — will be skipped")
        elif not _check_quota(engine, _pn):
            _log(f"  [CONFIG] {_pn}: quota exhausted — will be skipped")
        else:
            _log(f"  [CONFIG] {_pn}: active")

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

    combos = (
        veh.groupby(["make_n", "model_n", "year"], as_index=False)
        .agg({"engine_capacity": "first", "fuel": "first"})
    )
    combos["year"] = combos["year"].astype(int)
    _log(f"  {len(combos)} unique (make, model, year) combinations in vehicle_years")

    if enabled_makes is not None:
        _em = {m.upper().strip() for m in enabled_makes}
        combos = combos[combos["make_n"].isin(_em)]
        _log(f"  [CONFIG] scoped to {len(_em)} make(s): {', '.join(sorted(_em))} — {len(combos)} combos remain")
    else:
        _log(f"  [CONFIG] all makes selected — {combos['make_n'].nunique()} make(s), {len(combos)} combos")

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
    total = len(combos) - len(existing_keys)

    # ── Shared mutable state (all writes through the appropriate lock) ────────
    _model_web_cache: dict[str, dict | None] = _load_web_model_cache()
    provider_counts: dict[str, int] = {
        "duckduckgo": 0, "searxng": 0, "brave": 0, "tavily": 0,
    }
    _cache_lock    = threading.Lock()   # guards: cache dict + dirty_count + _save_cache
                                        #         also guards _model_web_cache saves
    _counters_lock = threading.Lock()   # guards: n_cached / n_fetched / n_failed
    _rows_lock     = threading.Lock()   # guards: rows_buffer + DB flush
    _prov_lock     = threading.Lock()   # guards: provider_counts

    n_cached = n_fetched = n_failed = dirty_count = web_model_dirty = _buckets_attempted = 0
    rows_buffer: list[dict] = []

    def _flush_rows() -> None:
        """Flush rows_buffer to DB. Must be called with _rows_lock held."""
        if rows_buffer:
            _upsert_rows(engine, rows_buffer[:], run_id=run_id)
            rows_buffer.clear()

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1 — pre-fetch web results per 5-year generation bucket per model
    # ─────────────────────────────────────────────────────────────────────────
    all_unique_buckets: list[tuple[str, str, int, int]] = []
    for (make, model), grp in combos.groupby(["make_n", "model_n"]):
        years = sorted(grp["year"].dropna().astype(int).unique())
        for bucket in sorted({(y // 5) * 5 for y in years}):
            bucket_years = [y for y in years if (y // 5) * 5 == bucket]
            # Skip bucket if every year-combo in it is already validated in the DB
            if all((str(make), str(model), y) in existing_keys for y in bucket_years):
                continue
            rep_year = bucket_years[len(bucket_years) // 2]
            all_unique_buckets.append((str(make), str(model), int(bucket), int(rep_year)))

    unique_buckets = [
        (m, mo, b, ry) for m, mo, b, ry in all_unique_buckets
        if f"{m}|{mo}|{b}" not in _model_web_cache
    ]
    already_cached = len(all_unique_buckets) - len(unique_buckets)
    _log(f"  Phase 1: {len(unique_buckets)} model-year buckets to fetch"
         f" ({already_cached} already cached, {WEB_PREFETCH_WORKERS} workers)…")

    def _prefetch_web(bucket_entry: tuple) -> None:
        nonlocal web_model_dirty, _buckets_attempted
        make, model, bucket, rep_year = bucket_entry
        wck = f"{make}|{model}|{bucket}"
        if _is_cancelled():
            return

        # If network was already down when this worker starts, wait before attempting
        if not _net_ok_event.is_set():
            if not _wait_for_net():
                with _cache_lock:
                    _buckets_attempted += 1
                if phase1_progress_callback:
                    phase1_progress_callback(_buckets_attempted, len(all_unique_buckets))
                return

        for net_retry in range(2):
            web_parsed: dict | None = None
            src = None
            any_net_error = False

            # Brave — primary paid provider
            if _is_enabled("brave") and _check_quota(engine, "brave"):
                try:
                    web_parsed = _brave_lookup(make, model, rep_year, cancel_event)
                    _increment_quota(engine, "brave")
                    if web_parsed:
                        src = "brave"
                        with _prov_lock:
                            provider_counts["brave"] += 1
                except Exception as exc:
                    if _is_net_error(exc):
                        any_net_error = True
                    else:
                        err_msg = str(exc).split("(")[0].strip().rstrip(":").strip() or type(exc).__name__
                        _log(f"    [WEB-ERR] Brave {make} {model} ({bucket}–{bucket+4}): {err_msg}")
                _interruptible_sleep(REQUEST_DELAY, cancel_event)

            if _is_cancelled():
                return

            # SearXNG — second if configured (localhost/self-hosted); no quota consumed
            if web_parsed is None and _is_enabled("searxng") and _check_quota(engine, "searxng"):
                try:
                    web_parsed = _searxng_lookup(make, model, rep_year, cancel_event)
                    if web_parsed:
                        src = "searxng"
                        with _prov_lock:
                            provider_counts["searxng"] += 1
                except Exception as exc:
                    if _is_net_error(exc):
                        any_net_error = True
                    else:
                        err_msg = str(exc).split("(")[0].strip().rstrip(":").strip() or type(exc).__name__
                        _log(f"    [WEB-ERR] SearXNG {make} {model} ({bucket}–{bucket+4}): {err_msg}")
                _interruptible_sleep(REQUEST_DELAY, cancel_event)

            if _is_cancelled():
                return

            # Tavily — second paid fallback; _check_quota returns False instantly if no key/quota
            if web_parsed is None and _is_enabled("tavily") and _check_quota(engine, "tavily"):
                try:
                    web_parsed = _tavily_lookup(make, model, rep_year, cancel_event)
                    _increment_quota(engine, "tavily")
                    if web_parsed:
                        src = "tavily"
                        with _prov_lock:
                            provider_counts["tavily"] += 1
                except Exception as exc:
                    if _is_net_error(exc):
                        any_net_error = True
                    else:
                        err_msg = str(exc).split("(")[0].strip().rstrip(":").strip() or type(exc).__name__
                        _log(f"    [WEB-ERR] Tavily {make} {model} ({bucket}–{bucket+4}): {err_msg}")
                _interruptible_sleep(REQUEST_DELAY, cancel_event)

            if _is_cancelled():
                return

            # DDG — last resort, free and unlimited
            if web_parsed is None and _is_enabled("duckduckgo") and _check_quota(engine, "duckduckgo"):
                try:
                    web_parsed = _duckduckgo_lookup(make, model, rep_year, cancel_event)
                    _increment_quota(engine, "duckduckgo")
                    if web_parsed:
                        src = "duckduckgo"
                        with _prov_lock:
                            provider_counts["duckduckgo"] += 1
                except Exception as exc:
                    if _is_net_error(exc):
                        any_net_error = True
                    else:
                        err_msg = str(exc).split("(")[0].strip().rstrip(":").strip() or type(exc).__name__
                        _log(f"    [WEB-ERR] DDG {make} {model} ({bucket}–{bucket+4}): {err_msg}")

            # Trigger network-down path only if at least one provider got a net error
            # and no provider found a result — wait for reconnect then retry the bucket once
            if any_net_error and web_parsed is None and not _is_cancelled() and net_retry == 0:
                _net_ok_event.clear()
                _log(f"    [NET] Network error on {make} {model} — waiting for reconnect…")
                if _wait_for_net():
                    _log(f"    [NET] Retrying {make} {model} {bucket}…")
                    continue  # second pass

            ah_val = web_parsed.get("ah") if web_parsed else None
            is_valid_result = web_parsed is not None and isinstance(ah_val, (int, float)) and 20 <= ah_val <= 250

            if is_valid_result and web_parsed:
                with _cache_lock:
                    _model_web_cache[wck] = web_parsed
                    web_model_dirty += 1
                    if web_model_dirty >= WEB_MODEL_SAVE_INTERVAL:
                        _save_web_model_cache(_model_web_cache)
                        web_model_dirty = 0
                _log(f"    [WEB/{src}] {make} {model} ({bucket}–{bucket+4}) Ah={web_parsed['ah']} tech={web_parsed['technology']}")
            elif web_parsed:
                _log(f"    [WEB-BAD] {make} {model} ({bucket}–{bucket+4}) Ah={ah_val} out of range — skipped")

            break

        # Always fires exactly once per bucket — outside the retry loop
        with _cache_lock:
            _buckets_attempted += 1
            if _buckets_attempted % 50 == 0:
                _log(f"  [P1] {_buckets_attempted}/{len(all_unique_buckets)} buckets processed…")
        if phase1_progress_callback:
            phase1_progress_callback(_buckets_attempted, len(all_unique_buckets))

    if phase in ("phase1", "both"):
        with ThreadPoolExecutor(max_workers=WEB_PREFETCH_WORKERS) as ex:
            list(ex.map(_prefetch_web, unique_buckets))

        # Always flush whatever is left after Phase 1 (covers cancel mid-phase too)
        with _cache_lock:
            _save_web_model_cache(_model_web_cache)

        web_hits = sum(1 for v in _model_web_cache.values() if v is not None)
        total_buckets = len(all_unique_buckets)
        if _is_cancelled():
            _log(f"  [CANCELLED] Phase 1 stopped early — {web_hits}/{total_buckets} buckets cached. Phase 2 skipped.")
            return {"fetched": 0, "cached": 0, "failed": 0, "provider_counts": dict(provider_counts)}
        else:
            _log(f"  Phase 1 complete — {web_hits}/{total_buckets} buckets matched via web search")

        if phase == "phase1":
            _log("  Phase 1 only — done. Run Phase 2 separately when ready.")
            return {"fetched": 0, "cached": 0, "failed": 0, "provider_counts": dict(provider_counts)}
    else:
        _log("  Skipping Phase 1 — running Phase 2 only using existing web cache.")

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2 — process all (make, model, year) combos concurrently
    # ─────────────────────────────────────────────────────────────────────────
    _log(f"  Phase 2: processing {total} combos with {MAX_WORKERS} workers…")

    def _process_combo(row: pd.Series) -> None:
        nonlocal n_cached, n_fetched, n_failed, dirty_count

        try:
            if not _wait_if_paused():
                return

            make_n  = str(row["make_n"])
            model_n = str(row["model_n"])
            year    = int(row["year"])

            if (make_n, model_n, year) in existing_keys:
                return

            key = _cache_key(make_n, model_n, year)

            # File cache hit
            with _cache_lock:
                if key in cache:
                    cached_val = cache[key]
                    if cached_val is not None:
                        with _rows_lock:
                            rows_buffer.append(cached_val)
                            if len(rows_buffer) >= 50:
                                _flush_rows()
                    with _counters_lock:
                        n_cached += 1
                    if progress_callback:
                        progress_callback(n_cached + n_fetched + n_failed, total, "cache", f"{make_n} {model_n} {year}")
                    return

            parsed: dict | None = None
            source_provider = "none"

            raw_cc   = row["engine_capacity"]
            raw_fuel = row["fuel"]
            try:
                engine_cc = int(float(raw_cc)) if pd.notna(raw_cc) else None
            except (ValueError, TypeError):
                engine_cc = None
            fuel_type = str(raw_fuel) if pd.notna(raw_fuel) else None

            try:
                # carquery: fill missing engine_cc only
                if not engine_cc and _check_quota(engine, "carquery"):
                    cq = _carquery_lookup(make_n, model_n, year, cancel_event)
                    _increment_quota(engine, "carquery")
                    if cq:
                        engine_cc = cq.get("engine_cc")
                        if not fuel_type:
                            fuel_type = cq.get("fuel")
                    _interruptible_sleep(REQUEST_DELAY, cancel_event)

                # Web cache — pre-fetched in Phase 1 per 5-year generation bucket
                if not _wait_if_paused():
                    return

                if parsed is None:
                    year_bucket = (year // 5) * 5
                    web_hit = _model_web_cache.get(f"{make_n}|{model_n}|{year_bucket}")
                    if web_hit:
                        parsed = web_hit
                        source_provider = "web_cached"

            except Exception as exc:
                _log(f"    [ERR] {make_n} {model_n} {year}: {exc}")
                parsed = None

            _combo_label = f"{make_n} {model_n} {year}"

            def _mark_failed() -> None:
                nonlocal n_failed, dirty_count
                _log(f"  [P2] {_combo_label} → no match")
                with _cache_lock:
                    cache[key] = None
                    dirty_count += 1
                    if dirty_count >= CACHE_SAVE_INTERVAL:
                        _save_cache(cache)
                        dirty_count = 0
                with _counters_lock:
                    n_failed += 1
                if progress_callback:
                    progress_callback(n_cached + n_fetched + n_failed, total, "none", _combo_label)

            if parsed is None:
                _mark_failed()
                return

            resolved = _resolve_battery_code(parsed, make_n)
            if resolved is None:
                _log(f"    [SKIP] {make_n} {model_n} {year} — could not resolve battery_code")
                _mark_failed()
                return

            battery_code, ah, technology = resolved
            _log(f"  [P2] {_combo_label} → Ah={ah} {technology or ''} ({source_provider})")
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

            with _cache_lock:
                cache[key] = db_row
                dirty_count += 1
                if dirty_count >= CACHE_SAVE_INTERVAL:
                    _save_cache(cache)
                    dirty_count = 0

            with _rows_lock:
                rows_buffer.append(db_row)
                if len(rows_buffer) >= 50:
                    _flush_rows()

            with _counters_lock:
                n_fetched += 1

            if progress_callback:
                progress_callback(n_cached + n_fetched + n_failed, total, source_provider, _combo_label)

        except Exception as exc:
            _log(f"    [FATAL-SKIP] row crashed unexpectedly: {exc}")
            with _counters_lock:
                n_failed += 1
            if progress_callback:
                progress_callback(n_cached + n_fetched + n_failed, total, "none", "")

    rows_list = [row for _, row in combos.iterrows()]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        list(ex.map(_process_combo, rows_list))

    # Final flushes
    with _rows_lock:
        _flush_rows()
    with _cache_lock:
        _save_cache(cache)

    was_cancelled = _is_cancelled()
    run_status = "cancelled" if was_cancelled else "completed"

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
