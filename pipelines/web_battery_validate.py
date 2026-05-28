"""
Web battery validation pipeline.

Queries external sources (carapi.app, then Brave Search) to find the
internet-accepted battery for each (make, model, year) combination that
does not already exist in web_battery_validation. Results are upserted
into the table so matcher.py can use them as Layer 0a.

Usage:
    python pipelines/web_battery_validate.py

Environment variables (in .env):
    DATABASE_URL   — PostgreSQL connection string (required)
    BRAVE_API_KEY  — Brave Search API key (required for search fallback)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

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

CACHE_FILE    = "cache/battery_validate_cache.json"
REQUEST_DELAY = 1.5   # seconds between API calls
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
TABLE_NAME    = "web_battery_validation"

CARAPI_TRIMS_URL = "https://carapi.app/api/trims?make={make}&model={model}&year={year}&verbose=yes&limit=50"
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

# Brave rate-limit: 429 → wait 30s and retry once
BRAVE_429_WAIT = 30

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
# Ah / technology parsers
# ---------------------------------------------------------------------------

_AH_RE   = re.compile(r"\b(\d{2,3})\s*[Aa][Hh]\b")
_CCA_RE  = re.compile(r"\b(\d{3,4})\s*(?:[Cc][Cc][Aa]|[Aa]\s*EN)\b")
_AGM_RE  = re.compile(r"\bAGM\b", re.IGNORECASE)
_EFB_RE  = re.compile(r"\bEFB\b", re.IGNORECASE)
_NS_RE   = re.compile(r"\bNS\b", re.IGNORECASE)
_DIN_RE  = re.compile(r"\bDIN\b", re.IGNORECASE)


def _parse_text(text: str) -> dict | None:
    """Extract battery specs from free text. Returns dict or None."""
    ah_hits = _AH_RE.findall(text)
    if not ah_hits:
        return None

    # Pick the most common Ah value mentioned
    ah = int(max(set(ah_hits), key=ah_hits.count))

    tech = "MF"
    if _AGM_RE.search(text):
        tech = "AGM"
    elif _EFB_RE.search(text):
        tech = "EFB"

    region = None
    if _NS_RE.search(text):
        region = "NS"
    elif _DIN_RE.search(text):
        region = "DIN"

    return {"ah": ah, "technology": tech, "region": region}


# ---------------------------------------------------------------------------
# carapi.app lookup
# ---------------------------------------------------------------------------

def _carapi_lookup(make: str, model: str, year: int) -> dict | None:
    """
    Query carapi.app trims endpoint. Returns parsed battery dict or None.
    carapi does not have a dedicated battery field, but trim descriptions
    sometimes include battery specs in the notes/specs payload.
    """
    url = CARAPI_TRIMS_URL.format(
        make=requests.utils.quote(make.title()),
        model=requests.utils.quote(model.title()),
        year=year,
    )
    try:
        resp = SESSION.get(url, timeout=15)
        if resp.status_code == 429:
            print(f"    [CARAPI] 429 — waiting 15s")
            time.sleep(15)
            resp = SESSION.get(url, timeout=15)
        if not resp.ok:
            return None
        data = resp.json()
        trims = data.get("data", [])
        if not trims:
            return None
        # Scan all trim descriptions/notes for battery specs
        full_text = " ".join(
            str(t.get("description", "")) + " " + str(t.get("specs", ""))
            for t in trims
        )
        return _parse_text(full_text) if full_text.strip() else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Brave Search lookup
# ---------------------------------------------------------------------------

def _brave_lookup(make: str, model: str, year: int) -> dict | None:
    """
    Query Brave Search for battery specs. Parses top result snippets.
    Returns parsed battery dict or None.
    """
    if not BRAVE_API_KEY:
        return None

    query = f"{make} {model} {year} car battery AH specifications"
    headers = {
        "Accept":              "application/json",
        "Accept-Encoding":     "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }
    params = {"q": query, "count": 5, "text_decorations": False}

    for attempt in range(2):
        try:
            resp = SESSION.get(
                BRAVE_SEARCH_URL, headers=headers, params=params, timeout=15
            )
            if resp.status_code == 429:
                wait = BRAVE_429_WAIT * (attempt + 1)
                print(f"    [BRAVE] 429 — waiting {wait}s")
                time.sleep(wait)
                continue
            if not resp.ok:
                return None
            results = resp.json().get("web", {}).get("results", [])
            combined = " ".join(
                r.get("title", "") + " " + r.get("description", "")
                for r in results
            )
            return _parse_text(combined) if combined.strip() else None
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Resolve parsed specs to a battery_code from battery_specs
# ---------------------------------------------------------------------------

def _resolve_battery_code(parsed: dict, make_n: str) -> tuple[str, int, str] | None:
    """
    Turn (ah, technology, region) from a web parse into a real battery_code.
    Returns (battery_code, ah, technology) or None.
    """
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

def _upsert_rows(rows: list[dict]) -> None:
    if not rows:
        return
    from db import engine
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        for row in rows:
            conn.execute(
                text(
                    f"""
                    INSERT INTO {TABLE_NAME}
                        (make_n, model_n, year, battery_code, ah, technology, source, validated_at)
                    VALUES
                        (:make_n, :model_n, :year, :battery_code, :ah, :technology, :source, :validated_at)
                    ON CONFLICT (make_n, model_n, year)
                    DO UPDATE SET
                        battery_code = EXCLUDED.battery_code,
                        ah           = EXCLUDED.ah,
                        technology   = EXCLUDED.technology,
                        source       = EXCLUDED.source,
                        validated_at = EXCLUDED.validated_at
                    """
                ),
                {**row, "validated_at": now},
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    from db import engine

    print("[START] web_battery_validate.py")

    # Load all unique (make_n, model_n, year) from vehicle_years
    veh = pd.read_sql(
        "SELECT DISTINCT"
        " UPPER(TRIM(make)) AS make_n,"
        " model AS raw_model,"
        " year"
        " FROM vehicle_years"
        " WHERE year IS NOT NULL",
        engine,
    )
    veh["model_n"] = veh["raw_model"].astype(str).apply(_norm_model_key)
    veh["year"]    = pd.to_numeric(veh["year"], errors="coerce").astype("Int64")
    veh = veh.dropna(subset=["make_n", "model_n", "year"])
    combos = veh[["make_n", "model_n", "year"]].drop_duplicates()
    print(f"  {len(combos)} unique (make, model, year) combinations in vehicle_years")

    # Load already-validated combos
    try:
        existing = pd.read_sql(
            f"SELECT make_n, model_n, year FROM {TABLE_NAME}", engine
        )
        existing["year"] = pd.to_numeric(existing["year"], errors="coerce").astype("Int64")
        existing_keys = set(
            zip(existing["make_n"], existing["model_n"], existing["year"].astype(int))
        )
    except Exception:
        existing_keys = set()
    print(f"  {len(existing_keys)} already validated — skipping")

    cache = _load_cache()
    new_rows: list[dict] = []
    n_cached = n_fetched = n_failed = 0

    for _, row in combos.iterrows():
        make_n  = str(row["make_n"])
        model_n = str(row["model_n"])
        year    = int(row["year"])
        key     = _cache_key(make_n, model_n, year)

        if (make_n, model_n, year) in existing_keys:
            continue

        # Check file cache
        if key in cache:
            cached = cache[key]
            if cached is not None:
                new_rows.append(cached)
            n_cached += 1
            continue

        print(f"  [FETCH] {make_n} {model_n} {year}")
        parsed = None

        # Source 1: carapi.app
        parsed = _carapi_lookup(make_n, model_n, year)
        if parsed:
            print(f"    [CARAPI] Ah={parsed['ah']} tech={parsed['technology']}")
        time.sleep(REQUEST_DELAY)

        # Source 2: Brave Search fallback
        if parsed is None:
            parsed = _brave_lookup(make_n, model_n, year)
            if parsed:
                print(f"    [BRAVE]  Ah={parsed['ah']} tech={parsed['technology']}")
            time.sleep(REQUEST_DELAY)

        if parsed is None:
            print(f"    [SKIP]   no result")
            cache[key] = None
            n_failed += 1
            _save_cache(cache)
            continue

        resolved = _resolve_battery_code(parsed, make_n)
        if resolved is None:
            print(f"    [SKIP]   could not resolve to battery_code")
            cache[key] = None
            n_failed += 1
            _save_cache(cache)
            continue

        battery_code, ah, technology = resolved
        source = "carapi" if _carapi_lookup.__doc__ and parsed else "brave_search"
        db_row = {
            "make_n":       make_n,
            "model_n":      model_n,
            "year":         year,
            "battery_code": battery_code,
            "ah":           ah,
            "technology":   technology,
            "source":       "web",
        }
        cache[key] = db_row
        new_rows.append(db_row)
        n_fetched += 1
        _save_cache(cache)

        # Flush every 50 rows to avoid losing progress
        if len(new_rows) >= 50:
            _upsert_rows(new_rows)
            new_rows = []

    # Final flush
    _upsert_rows(new_rows)

    print(
        f"\n[END] Done — {n_fetched} fetched, {n_cached} from cache, {n_failed} no result"
    )


if __name__ == "__main__":
    main()
