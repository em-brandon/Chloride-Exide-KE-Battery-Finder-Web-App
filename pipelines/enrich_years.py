"""
CRSP Pipeline — Stage 2: Year Enrichment

Reads battery_lookup_dataset.csv (output of dataprep.py), queries 5 external
sources to find production year ranges for each unique make/model pair, then
writes results to vehicle_years_staging for admin review before committing.

Can be run:
  - From the admin UI (admin_router.py spawns a background thread and calls main())
  - From the CLI: python pipelines/enrich_years.py

External sources (in priority order):
  1. fueleconomy.gov bulk CSV  — exact per-year data (US EPA, 1984–present)
  2. CarAPI                    — community year ranges
  3. Wikipedia API             — article extracts with year mentions
  4. Wikidata SPARQL           — structured production dates
  5. NHTSA VPIC                — fallback model list (confirms model exists, no per-year data)
"""

import os
import json
import re
import threading
import time
import uuid
import urllib3

import pandas as pd
import requests
from rapidfuzz import process, fuzz

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =========================
# CONFIG
# =========================
INPUT_CSV             = "battery_lookup_dataset.csv"
OUTPUT_CSV            = "vehicle_years.csv"          # still written for CLI use
OUTPUT_EXCEL          = "vehicle_years.xlsx"
UNMATCHED_CSV         = "unmatched_models.csv"
CACHE_FILE            = "cache/year_cache.json"
FUELECONOMY_CSV_URL   = "https://www.fueleconomy.gov/feg/epadata/vehicles.csv"
FUELECONOMY_CSV       = "cache/fueleconomy_vehicles.csv"
CURRENT_YEAR          = 2026
REQUEST_DELAY         = 1.0
MATCH_SCORE_THRESHOLD = 45

NHTSA_ALL_MODELS   = "https://vpic.nhtsa.dot.gov/api/vehicles/GetModelsForMake/{make}?format=json"
WIKI_SEARCH_URL    = "https://en.wikipedia.org/w/api.php"
WIKIDATA_SPARQL    = "https://query.wikidata.org/sparql"
CARAPI_MODELS_URL  = "https://carapi.app/api/models?make={make}&verbose=yes&limit=200"

SESSION = requests.Session()
SESSION.verify = False
SESSION.headers["User-Agent"] = (
    "BatteryFinderBot/1.0 (battery-finder research; contact: battery-finder-bot@example.com)"
)

# =========================
# MAKE NAME MAPS
# =========================
MAKE_MAP = {
    "LANDROVER":        "land rover",
    "MERCEDES":         "mercedes-benz",
    "MARUTI SUZUKI":    "suzuki",
    "GREAT WALL":       "great wall motors",
    "MITSUBISHI FUSO":  "mitsubishi",
    "NISSAN DIESEL/UD": "nissan",
    "IVECO DAILY":      "iveco",
    "SAIC MOTORS":      "saic",
    "BRABUS":           "mercedes-benz",
}

FE_MAKE_MAP = {
    "BMW":               "BMW",
    "GMC":               "GMC",
    "MINI":              "MINI",
    "LANDROVER":         "Land Rover",
    "LAND ROVER":        "Land Rover",
    "MERCEDES":          "Mercedes-Benz",
    "MERCEDES-BENZ":     "Mercedes-Benz",
    "BRABUS":            "Mercedes-Benz",
    "NISSAN DIESEL/UD":  "Nissan",
    "MITSUBISHI FUSO":   None,
    "GREAT WALL":        None,
    "SAIC MOTORS":       None,
    "MARUTI SUZUKI":     None,
    "IVECO DAILY":       None,
    "PEUGEOT":           None,
    "CITROEN":           None,
    "RENAULT":           None,
    "HAVAL":             None,
}


def to_nhtsa_make(make):
    return MAKE_MAP.get(make.upper(), make.lower())


def to_fe_make(make):
    upper = make.strip().upper()
    if upper in FE_MAKE_MAP:
        return FE_MAKE_MAP[upper]
    return make.strip().title()


def to_search_make(make: str) -> str:
    """Normalise make name for external search queries (Wikipedia / Wikidata)."""
    mapped = MAKE_MAP.get(make.strip().upper())
    if mapped:
        return mapped.title()
    return make.strip().title()


def extract_search_model(make: str, model_name: str) -> str:
    """
    Return the shortest unambiguous base model name suitable for a web search.
    Strips engine codes (any token containing a digit) and common trim words so
    queries like 'Toyota Hilux 2GD automobile' become 'Toyota Hilux automobile'.
    """
    _TRIM_STOP = {
        'S', 'SE', 'SL', 'SR', 'GT', 'RS', 'GTS', 'TRD',
        'LINE', 'SPORT', 'SPORTS', 'ADVANCED', 'AMG', 'QUATTRO', 'AWD',
        '4MATIC', 'LIMITED', 'EDITION', 'PACKAGE', 'PLUS', 'BLACK', 'WHITE',
        'STYLE', 'PREMIUM', 'LUXURY', 'SIGNATURE', 'EXCLUSIVE', 'TECHNO',
        'MIDNIGHT', 'ULTIMATE', 'BASE', 'CLASSIC', 'ELITE', 'COMFORT',
        'ELEGANCE', 'EXECUTIVE', 'PROGRESSIVE', 'DYNAMIC', 'URBAN',
    }
    base = extract_base_model(make, model_name)
    clean_tokens = []
    for token in base.split():
        if re.search(r'\d', token):
            break                      # engine codes start here — stop
        if token.upper() in _TRIM_STOP:
            break
        clean_tokens.append(token)
    return ' '.join(clean_tokens) if clean_tokens else base


# =========================
# SOURCE 1 — NHTSA VPIC
# =========================
def fetch_nhtsa_models(make, log=print):
    nhtsa_make = to_nhtsa_make(make)
    url = NHTSA_ALL_MODELS.format(make=requests.utils.quote(nhtsa_make))
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json().get("Results", [])
    except Exception as e:
        log(f"    [NHTSA WARN] {make}: {e}")
    return []


# =========================
# SOURCE 2 — WIKIPEDIA API
# =========================
_wiki_skip_until = 0

# Tier 1 — explicit two-year production range
# Uses [\s\S]{0,50}? (non-greedy any-char) so brand names / month words between
# the keyword and the year don't break the match.
_WIKI_RANGE_PATTERNS = [
    r'(?:produc|manufactur|built|made)[\s\S]{0,50}?(?:from|between)\s+(\d{4})\s*(?:to|and|[-–—])\s*(\d{4})',
    r'production[\s\S]{0,15}?(\d{4})\s*[-–—]\s*(\d{4})',
    r'\b(\d{4})\s*[–—]\s*(\d{4})\b',   # standalone em/en-dash range anywhere in extract
]

# Tier 2 — open-ended "since / introduced / launched YEAR"
_WIKI_SINCE_PATTERNS = [
    r'(?:since|introduc|launch|debut|unveil)[\s\S]{0,25}?(\d{4})',
    r'\bfrom\s+(\d{4})\b',
]


def _parse_wiki_years(extract: str, page_title: str, make: str, model: str, log) -> tuple:
    """
    Tiered Wikipedia year extractor.

    Tier 1 — explicit range patterns  (e.g. "produced from 2010 to 2018")
    Tier 2 — open-ended since/from    (e.g. "manufactured since 2010")
    Tier 3 — year-cluster fallback    (all years 1960-present; densest 40-yr window)

    Returns (year_from, year_to) or (None, None).
    """
    # Tier 1 — two-year range
    for pat in _WIKI_RANGE_PATTERNS:
        m = re.search(pat, extract, re.IGNORECASE)
        if not m:
            continue
        try:
            yf, yt = int(m.group(1)), int(m.group(2))
            if 1960 <= yf <= CURRENT_YEAR and 1960 <= yt <= CURRENT_YEAR and yf <= yt <= yf + 50:
                log(f"    [Wiki] '{page_title}' → {yf}–{yt} [range]")
                return yf, yt
        except (ValueError, IndexError):
            continue

    # Tier 2 — open-ended start year
    for pat in _WIKI_SINCE_PATTERNS:
        m = re.search(pat, extract, re.IGNORECASE)
        if not m:
            continue
        try:
            yf = int(m.group(1))
            if 1960 <= yf <= CURRENT_YEAR:
                log(f"    [Wiki] '{page_title}' → since {yf} [since-pattern]")
                return yf, None
        except (ValueError, IndexError):
            continue

    # Tier 3 — cluster fallback: avoid picking up company founding years (pre-1960)
    # by restricting to modern automotive era, then find the densest 40-year window.
    all_years = sorted(set(
        int(y) for y in re.findall(r'\b(19[6-9]\d|20[0-2]\d)\b', extract)
    ))
    if len(all_years) >= 2:
        best_window: list[int] = []
        for base in all_years:
            window = [y for y in all_years if base <= y <= base + 40]
            if len(window) > len(best_window):
                best_window = window
        if len(best_window) >= 2:
            log(f"    [Wiki] '{page_title}' → {best_window[0]}–{best_window[-1]} [cluster/{len(best_window)} yrs]")
            return best_window[0], best_window[-1]

    log(f"    [Wiki] '{page_title}' — no year pattern matched")
    return None, None


def get_years_from_wikipedia(make, model_name, log=print, rate_limit_counter=None):
    global _wiki_skip_until
    if time.time() < _wiki_skip_until:
        remaining = int(_wiki_skip_until - time.time())
        log(f"    [Wiki] Skipping (cooling down for {remaining}s more)")
        return None, None

    search_make  = to_search_make(make)
    search_model = extract_search_model(make, model_name)
    query = f"{search_make} {search_model} automobile"
    log(f"    [Wiki] query: '{query}'")

    params = {"action": "query", "list": "search", "srsearch": query,
              "srlimit": 1, "format": "json", "utf8": 1}
    for attempt in range(3):
        try:
            r = SESSION.get(WIKI_SEARCH_URL, params=params, timeout=10)
            if r.status_code == 429:
                if rate_limit_counter is not None:
                    rate_limit_counter["wikipedia"] = rate_limit_counter.get("wikipedia", 0) + 1
                wait = 5 * (attempt + 1)   # 5s / 10s / 15s — gentler than 30/60/90
                log(f"    [Wiki] 429 rate-limit, waiting {wait}s...")
                time.sleep(wait)
                if attempt == 2:
                    _wiki_skip_until = time.time() + 120
                    log("    [Wiki] Repeated 429s — pausing Wikipedia for 2 minutes")
                continue
            r.raise_for_status()
            results = r.json().get("query", {}).get("search", [])
            if not results:
                log(f"    [Wiki] no search results for '{query}'")
                return None, None
            page_title = results[0]["title"]
            params2 = {"action": "query", "prop": "extracts", "exintro": True,
                       "titles": page_title, "format": "json", "utf8": 1}
            r2 = SESSION.get(WIKI_SEARCH_URL, params=params2, timeout=10)
            if r2.status_code == 429:
                if rate_limit_counter is not None:
                    rate_limit_counter["wikipedia"] = rate_limit_counter.get("wikipedia", 0) + 1
                wait = 5 * (attempt + 1)
                log(f"    [Wiki] 429 rate-limit, waiting {wait}s...")
                time.sleep(wait)
                if attempt == 2:
                    _wiki_skip_until = time.time() + 120
                    log("    [Wiki] Repeated 429s — pausing Wikipedia for 2 minutes")
                continue
            r2.raise_for_status()
            pages = r2.json().get("query", {}).get("pages", {})
            extract = next(iter(pages.values()), {}).get("extract", "")
            yf, yt = _parse_wiki_years(extract, page_title, make, model_name, log)
            if yf:
                return yf, yt
        except Exception as e:
            log(f"    [Wiki WARN] {make} {model_name}: {e}")
            break
    return None, None


# =========================
# SOURCE 3 — WIKIDATA SPARQL
# =========================
def get_years_from_wikidata(make, model_name, log=print, rate_limit_counter=None):
    # Use the cleaned base model (no engine codes) so the label FILTER can match
    # Wikidata entity names like "Audi A1 Sportback", not "Audi A1 Sportback 1.0 TFSI"
    search_model = extract_search_model(make, model_name)
    search_make_word = to_search_make(make).split()[0].lower()

    # P571 = inception (production start year) — replaces the incorrect P2047 (duration)
    # P582 = end time (production end year)
    sparql = f"""
    SELECT ?yearStart ?yearEnd WHERE {{
      ?car wdt:P31/wdt:P279* wd:Q3231690 .
      ?car rdfs:label ?label .
      FILTER(LANG(?label) = "en")
      FILTER(CONTAINS(LCASE(?label), "{search_model.lower()}"))
      FILTER(CONTAINS(LCASE(?label), "{search_make_word}"))
      OPTIONAL {{ ?car wdt:P571 ?yearStart . }}
      OPTIONAL {{ ?car wdt:P582 ?yearEnd . }}
    }} LIMIT 1
    """
    log(f"    [Wikidata] query label contains: '{search_make_word}' + '{search_model.lower()}'")
    for attempt in range(3):
        try:
            resp = SESSION.get(
                WIKIDATA_SPARQL,
                params={"query": sparql, "format": "json"},
                timeout=20,
                headers={"Accept": "application/sparql-results+json"},
            )
            if resp.status_code == 429:
                if rate_limit_counter is not None:
                    rate_limit_counter["wikidata"] = rate_limit_counter.get("wikidata", 0) + 1
                wait = 10 * (attempt + 1)   # 10s / 20s / 30s
                log(f"    [Wikidata] 429 rate-limit, waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            bindings = resp.json().get("results", {}).get("bindings", [])
            if bindings:
                yf = bindings[0].get("yearStart", {}).get("value")
                yt = bindings[0].get("yearEnd",   {}).get("value")
                yf = int(yf[:4]) if yf else None
                yt = int(yt[:4]) if yt else None
                if yf:
                    return yf, yt
            log(f"    [Wikidata] no bindings returned")
            return None, None
        except Exception as e:
            log(f"    [Wikidata WARN] {make} {model_name}: {e}")
            break
    return None, None


# =========================
# SOURCE 4 — CARAPI.APP
# =========================
def fetch_carapi_models(make, log=print):
    nhtsa_make = to_nhtsa_make(make)
    url = CARAPI_MODELS_URL.format(make=requests.utils.quote(nhtsa_make))
    for attempt in range(3):
        try:
            resp = SESSION.get(url, timeout=15)
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                log(f"    [CarAPI] 429 rate-limit for {make}, waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code == 200:
                return resp.json().get("data", [])
            log(f"    [CarAPI WARN] {make}: HTTP {resp.status_code}")
            return []
        except Exception as e:
            log(f"    [CarAPI WARN] {make}: {e}")
            if attempt < 2:
                time.sleep(5)
    return []


# =========================
# SOURCE 5 — FUELECONOMY.GOV
# =========================

# In-process LRU cache — survives across pipeline runs within the same server process.
# Invalidated by invalidate_fueleconomy_cache() when new data is downloaded via admin UI.
_fe_df_cache: dict = {}


def invalidate_fueleconomy_cache() -> None:
    _fe_df_cache.clear()


def _load_fe_df_from_db(db) -> pd.DataFrame:
    if "df" not in _fe_df_cache:
        from models import FueleconomyVehicle
        rows = db.query(
            FueleconomyVehicle.year,
            FueleconomyVehicle.make,
            FueleconomyVehicle.model,
        ).all()
        _fe_df_cache["df"] = pd.DataFrame(rows, columns=["year", "make", "model"])
    return _fe_df_cache["df"]


def load_fueleconomy_data(log=print, db=None):
    """
    Load fueleconomy.gov vehicle data.

    When called from the admin pipeline (db provided): loads from the DB table that was
    populated via the Download button in the admin UI. The first call per process populates
    an in-process cache so subsequent pipeline runs skip the DB round-trip entirely.

    When called from the CLI (no db): falls back to the local CSV file, downloading it
    first if absent (original behaviour, kept for offline/script use).
    """
    if db is not None:
        df = _load_fe_df_from_db(db)
        if not df.empty:
            source = "in-process cache" if len(_fe_df_cache) > 1 else "DB"
            log(f"  [FE] Loaded {len(df):,} records from {source}")
            return df
        log("  [FE] No fueleconomy data in DB — use the Download button in the admin UI first")
        return pd.DataFrame(columns=["year", "make", "model"])

    # CLI / fallback path: use the local CSV file (auto-download if missing)
    if os.path.exists(FUELECONOMY_CSV):
        log(f"  [FE] Loading cached {FUELECONOMY_CSV}...")
    else:
        log("  [FE] Downloading fueleconomy.gov vehicles CSV...")
        try:
            resp = SESSION.get(FUELECONOMY_CSV_URL, timeout=120)
            resp.raise_for_status()
            os.makedirs("cache", exist_ok=True)
            with open(FUELECONOMY_CSV, "wb") as f:
                f.write(resp.content)
            log(f"  [FE] Downloaded {len(resp.content) // 1024:,} KB")
        except Exception as e:
            log(f"  [FE] Download FAILED: {e}")
            return pd.DataFrame(columns=["year", "make", "model"])
    try:
        return pd.read_csv(
            FUELECONOMY_CSV,
            usecols=["year", "make", "model"],
            dtype={"year": int, "make": str, "model": str},
        )
    except Exception as e:
        log(f"  [FE] Could not read CSV: {e}")
        return pd.DataFrame(columns=["year", "make", "model"])


def _update_cache_meta(db, key, file_size_bytes=None, record_count=None):
    """Update the enrichment_cache_meta row for key. Safe to call with no db."""
    if db is None:
        return
    try:
        from datetime import datetime, timezone
        from sqlalchemy import text as sa_text
        now = datetime.now(tz=timezone.utc)
        db.execute(
            sa_text(
                "UPDATE enrichment_cache_meta SET downloaded_at=:ts, file_size_bytes=:sz, "
                "record_count=:rc, updated_at=:ts WHERE key=:key"
            ),
            {"ts": now, "sz": file_size_bytes, "rc": record_count, "key": key},
        )
        db.commit()
    except Exception:
        pass  # non-fatal; pipeline continues even if meta update fails


# =========================
# HELPERS
# =========================
def extract_base_model(make, model_name):
    name = model_name.strip()
    for prefix in [make.strip(), make.split()[0].strip()]:
        if name.upper().startswith(prefix.upper()):
            name = name[len(prefix):].strip()
            break
    tokens = name.split()
    return " ".join(tokens[:2]) if tokens else model_name


def lookup_years_fueleconomy(make, model_name, fe_df):
    if fe_df.empty:
        return None
    fe_make = to_fe_make(make)
    if fe_make is None:
        return None
    make_df = fe_df[fe_df["make"].str.strip().str.lower() == fe_make.lower()]
    if make_df.empty:
        return None
    unique_models = make_df["model"].dropna().unique().tolist()
    base_name = extract_base_model(make, model_name)
    result = process.extractOne(base_name, unique_models, scorer=fuzz.token_set_ratio)
    if result is None or result[1] < MATCH_SCORE_THRESHOLD:
        return None
    matched_model = result[0]
    years = sorted(
        make_df[make_df["model"] == matched_model]["year"]
        .dropna().astype(int).unique().tolist()
    )
    return years if years else None


def best_model_match(our_model, nhtsa_models):
    if not nhtsa_models:
        return None, 0
    names = [m.get("Model_Name", "") for m in nhtsa_models]
    result = process.extractOne(our_model, names, scorer=fuzz.token_set_ratio)
    if result is None or result[1] < MATCH_SCORE_THRESHOLD:
        return None, 0
    return result[0], result[1]


def lookup_years(make, model_name, carapi_models, fe_df, log=print, rate_limit_counter=None):
    """Try sources in priority order. Returns (years_list, source)."""

    # ── fueleconomy.gov ────────────────────────────────────────────────────────
    years = lookup_years_fueleconomy(make, model_name, fe_df)
    if years:
        log(f"      → fueleconomy: {years[0]}–{years[-1]} ({len(years)} yrs)")
        return years, "fueleconomy"
    else:
        fe_make = to_fe_make(make)
        reason = "make not in EPA data" if fe_make is None else (
            "fueleconomy DB empty" if fe_df.empty else "no fuzzy match"
        )
        log(f"      → fueleconomy: miss ({reason})")

    # ── CarAPI ─────────────────────────────────────────────────────────────────
    if carapi_models:
        ca_names = [m.get("name", "") for m in carapi_models]
        result = process.extractOne(model_name, ca_names, scorer=fuzz.token_set_ratio)
        if result and result[1] >= MATCH_SCORE_THRESHOLD:
            best = carapi_models[result[2]]
            yf = best.get("year_first") or best.get("year")
            yt = best.get("year_last")
            if yf:
                yf = int(yf)
                yt = min(int(yt), CURRENT_YEAR) if yt else CURRENT_YEAR
                log(f"      → carapi: {yf}–{yt} (matched '{result[0]}', score {result[1]})")
                return list(range(yf, yt + 1)), "carapi"
        score = result[1] if result else 0
        log(f"      → carapi: miss (best score {score} < {MATCH_SCORE_THRESHOLD})")
    else:
        log(f"      → carapi: miss (no models for make)")

    # ── Wikipedia ──────────────────────────────────────────────────────────────
    yf, yt = get_years_from_wikipedia(make, model_name, log=log, rate_limit_counter=rate_limit_counter)
    if yf:
        yt = min(yt, CURRENT_YEAR) if yt else CURRENT_YEAR
        log(f"      → wikipedia: {yf}–{yt}")
        return list(range(yf, yt + 1)), "wikipedia"
    log(f"      → wikipedia: miss")
    time.sleep(REQUEST_DELAY)

    # ── Wikidata ───────────────────────────────────────────────────────────────
    yf, yt = get_years_from_wikidata(make, model_name, log=log, rate_limit_counter=rate_limit_counter)
    if yf:
        yt = min(yt, CURRENT_YEAR) if yt else CURRENT_YEAR
        log(f"      → wikidata: {yf}–{yt}")
        return list(range(yf, yt + 1)), "wikidata"
    log(f"      → wikidata: miss")
    time.sleep(REQUEST_DELAY)

    log(f"      → all sources exhausted")
    return None, None


# =========================
# STAGING WRITER
# =========================
def write_to_staging(db, run_id, enriched_rows):
    """
    Upsert enriched rows into vehicle_years_staging.

    For each row:
    - new row (no match in vehicle_years)      → is_valid=1, conflict=0
    - same key, identical values               → skipped (no insert)
    - same key, different engine_cc or fuel    → conflict=1, conflict_detail=JSON
    """
    import json as _json
    from datetime import datetime, timezone
    from sqlalchemy import text as sa_text

    now = datetime.now(tz=timezone.utc)
    inserted = skipped = conflict = 0

    # Load existing vehicle_years into a dict for fast lookup
    rows = db.execute(
        sa_text("SELECT make, model, year, engine_capacity, fuel, source FROM vehicle_years")
    ).fetchall()
    existing = {
        (r.make, r.model, r.year): {
            "engine_capacity": r.engine_capacity,
            "fuel": r.fuel,
            "source": r.source,
        }
        for r in rows
    }

    for row in enriched_rows:
        key = (row["make"], row["model"], row["year"])
        current = existing.get(key)

        if current is not None:
            ec_same = current["engine_capacity"] == row.get("engine_capacity")
            fuel_same = (current["fuel"] or "").lower() == (row.get("fuel") or "").lower()
            if ec_same and fuel_same:
                skipped += 1
                continue
            is_conflict = True
            conflict_detail = _json.dumps({
                "current": current,
                "staged": {
                    "engine_capacity": row.get("engine_capacity"),
                    "fuel": row.get("fuel"),
                    "source": row.get("source"),
                },
            })
            conflict += 1
        else:
            is_conflict = False
            conflict_detail = None

        db.execute(
            sa_text("""
                INSERT INTO vehicle_years_staging
                    (run_id, make, model, year, engine_capacity, fuel, source,
                     staged_at, is_valid, conflict, conflict_detail)
                VALUES
                    (:run_id, :make, :model, :year, :ec, :fuel, :source,
                     :now, true, :conflict, :conflict_detail)
                ON CONFLICT (make, model, year) DO UPDATE SET
                    run_id=EXCLUDED.run_id,
                    engine_capacity=EXCLUDED.engine_capacity,
                    fuel=EXCLUDED.fuel,
                    source=EXCLUDED.source,
                    staged_at=EXCLUDED.staged_at,
                    is_valid=true,
                    conflict=EXCLUDED.conflict,
                    conflict_detail=EXCLUDED.conflict_detail
            """),
            {
                "run_id": run_id,
                "make": row["make"],
                "model": row["model"],
                "year": row["year"],
                "ec": row.get("engine_capacity"),
                "fuel": row.get("fuel"),
                "source": row.get("source"),
                "now": now,
                "conflict": is_conflict,
                "conflict_detail": conflict_detail,
            },
        )
        inserted += 1

    db.commit()
    return {"staged": inserted, "skipped_unchanged": skipped, "conflicts": conflict}


# =========================
# MAIN — callable by admin_router.py
# =========================
def main(
    run_id=None,
    db=None,
    input_csv=INPUT_CSV,
    log_callback=None,
    progress_callback=None,
    cancel_event: threading.Event = None,
    pause_event: threading.Event = None,
):
    """
    Run the full year enrichment pipeline.

    Parameters
    ----------
    run_id          : str   — UUID for this run (generated if not supplied)
    db              : SQLAlchemy Session — used to write staging rows + cache meta
    input_csv       : str   — path to battery_lookup_dataset.csv
    log_callback    : callable(str) — receives log lines (default: print)
    progress_callback : callable(processed, total, make, model) — progress updates
    cancel_event    : threading.Event — set to abort the run
    pause_event     : threading.Event — set to pause, clear to resume

    Returns
    -------
    dict with keys: total_pairs, enriched, not_found, conflicts, staged, source_counts
    """
    if run_id is None:
        run_id = str(uuid.uuid4())
    log = log_callback or print

    def _check_cancel():
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Pipeline cancelled")

    def _check_pause():
        while pause_event and pause_event.is_set():
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Pipeline cancelled")
            time.sleep(0.5)

    # ── Load cache ──────────────────────────────────────────────────────────
    os.makedirs("cache", exist_ok=True)
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except FileNotFoundError:
        cache = {}
    for key in ("nhtsa", "carapi", "years"):
        if key not in cache:
            cache[key] = {}

    # Strip null entries so pairs that previously failed are retried with fresh API calls
    null_entries = [k for k, v in cache["years"].items() if v[0] is None]
    for k in null_entries:
        del cache["years"][k]
    if null_entries:
        log(f"Cache: cleared {len(null_entries)} unresolved entries — will retry against APIs")
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)

    log(f"Cache loaded — {len(cache['years'])} year entries, "
        f"{len(cache['nhtsa'])} NHTSA makes, {len(cache['carapi'])} CarAPI makes")

    # ── Load input CSV ──────────────────────────────────────────────────────
    if not os.path.exists(input_csv):
        raise FileNotFoundError(f"Input not found: {input_csv}. Run dataprep.py first.")
    try:
        df = pd.read_csv(input_csv, encoding='utf-8')
    except UnicodeDecodeError:
        df = pd.read_csv(input_csv, encoding='latin-1')
    unique_makes = df["make"].str.upper().unique().tolist()
    unique_pairs = df[["make", "model"]].drop_duplicates()
    total_pairs  = len(unique_pairs)
    log(f"Loaded {len(df):,} rows, {len(unique_makes)} makes, {total_pairs} unique make+model pairs")

    # ── Stage 1: fueleconomy.gov CSV ────────────────────────────────────────
    _check_cancel()
    log("[Stage 1/4] Loading fueleconomy.gov vehicle data...")
    fe_df = load_fueleconomy_data(log=log, db=db)
    log(f"  {len(fe_df):,} vehicle-year records loaded")

    # ── Stage 2: NHTSA VPIC model lists ─────────────────────────────────────
    _check_cancel()
    log(f"[Stage 2/4] Fetching NHTSA model lists for {len(unique_makes)} makes...")
    nhtsa_fetched = 0
    for make_idx, make in enumerate(unique_makes, start=1):
        _check_cancel()
        _check_pause()
        if make in cache["nhtsa"]:
            log(f"  [{make_idx}/{len(unique_makes)}] [CACHED] {make}")
            continue
        log(f"  [{make_idx}/{len(unique_makes)}] [FETCH]  {make} ...")
        models = fetch_nhtsa_models(make, log=log)
        cache["nhtsa"][make] = models
        nhtsa_fetched += 1
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        time.sleep(REQUEST_DELAY)

    # Update NHTSA cache meta if we fetched anything new
    if nhtsa_fetched and db is not None:
        _update_cache_meta(db, key="year_cache")

    # ── Stage 3: CarAPI model lists ─────────────────────────────────────────
    _check_cancel()
    log(f"[Stage 3/4] Fetching CarAPI model lists for {len(unique_makes)} makes...")
    for make_idx, make in enumerate(unique_makes, start=1):
        _check_cancel()
        _check_pause()
        if make in cache["carapi"]:
            log(f"  [{make_idx}/{len(unique_makes)}] [CACHED] {make}")
            continue
        log(f"  [{make_idx}/{len(unique_makes)}] [FETCH]  {make} ...")
        ca_models = fetch_carapi_models(make, log=log)
        cache["carapi"][make] = ca_models
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        time.sleep(REQUEST_DELAY)

    # ── Stage 4: Year lookup per unique pair ─────────────────────────────────
    _check_cancel()
    log(f"[Stage 4/4] Looking up years for {total_pairs} unique make+model pairs...")

    # Pre-group original CSV rows by pair key so we can expand immediately on hit
    has_fuel_col = "fuel" in df.columns
    pair_rows: dict[str, list] = {}
    for _, orig in df.iterrows():
        m  = str(orig.get("make",  "")).strip().upper()
        mo = str(orig.get("model", "")).strip()
        pk = f"{m}||{mo}"
        if pk not in pair_rows:
            pair_rows[pk] = []
        pair_rows[pk].append(orig)

    FLUSH_EVERY = 50   # write to staging every N pairs so partial runs are recoverable

    pairs_done        = {}
    pairs_count       = 0
    processed         = 0
    rate_limit_counter = {"wikipedia": 0, "wikidata": 0}
    cache_hit_counts  = {"fueleconomy": 0, "carapi": 0, "wikipedia": 0, "wikidata": 0, "nhtsa": 0}

    expanded_rows:                  list  = []
    unmatched_info: dict[tuple, str]      = {}
    src_counts:     dict[str, int]        = {}
    pending_rows:   list                  = []   # buffer for next flush
    total_staged    = 0

    def _flush_pending() -> None:
        nonlocal pending_rows, total_staged
        if not pending_rows or db is None:
            return
        result = write_to_staging(db, run_id, pending_rows)
        total_staged += result.get("staged", 0)
        log(
            f"  [Staging] flushed {len(pending_rows)} rows → "
            f"{result['staged']} staged, {result['skipped_unchanged']} unchanged, "
            f"{result['conflicts']} conflicts  (total staged so far: {total_staged})"
        )
        pending_rows = []

    for _, row in unique_pairs.iterrows():
        # Check cancel before each pair; flush pending so partial work is preserved
        if cancel_event and cancel_event.is_set():
            _flush_pending()
            raise InterruptedError("Pipeline cancelled")
        _check_pause()

        make     = str(row.get("make", "")).strip().upper()
        model    = str(row.get("model", "")).strip()
        pair_key = f"{make}||{model}"
        pairs_count += 1

        nhtsa_models = cache["nhtsa"].get(make, [])
        ca_models    = cache["carapi"].get(make, [])

        matched_name, _ = best_model_match(model, nhtsa_models)
        if not matched_name:
            base_model = extract_base_model(make, model)
            if base_model.upper() != model.upper():
                matched_name, _ = best_model_match(base_model, nhtsa_models)
        lookup_name = matched_name if matched_name else extract_base_model(make, model)

        year_key = f"{make}|{lookup_name}"
        if year_key in cache["years"]:
            years_list, src = cache["years"][year_key]
            if src and src in cache_hit_counts:
                cache_hit_counts[src] = cache_hit_counts.get(src, 0) + 1
            log(f"  [{pairs_count}/{total_pairs}] [CACHED] {make} {lookup_name} ({src})")
        else:
            log(f"  [{pairs_count}/{total_pairs}] [LOOKUP] {make} {lookup_name} ...")
            years_list, src = lookup_years(
                make, lookup_name, ca_models, fe_df, log=log,
                rate_limit_counter=rate_limit_counter,
            )
            if years_list is not None:
                cache["years"][year_key] = [years_list, src]
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cache, f)
            status = f"{len(years_list)} years via {src}" if years_list else "not found"
            log(f"  [{pairs_count}/{total_pairs}] -> {status}")
            time.sleep(REQUEST_DELAY)

        pairs_done[pair_key] = (years_list, src)

        # Expand this pair immediately and buffer for staging
        if years_list:
            src_counts[src] = src_counts.get(src, 0) + 1
            for orig in pair_rows.get(pair_key, []):
                for yr in years_list:
                    row_dict = {
                        "make":            make,
                        "model":           model,
                        "year":            yr,
                        "engine_capacity": orig.get("engine_capacity"),
                        "fuel":            orig.get("fuel"),
                        "source":          src,
                    }
                    expanded_rows.append(row_dict)
                    pending_rows.append(row_dict)
        else:
            for orig in pair_rows.get(pair_key, []):
                fuel_val = str(orig.get("fuel", "")).strip() if has_fuel_col else ""
                unmatched_info[
                    (str(orig.get("make", "")), str(orig.get("model", "")))
                ] = fuel_val

        processed += 1
        if progress_callback:
            progress_callback(processed, total_pairs, make, model)

        # Periodic flush every FLUSH_EVERY pairs
        if pairs_count % FLUSH_EVERY == 0:
            _flush_pending()

    # Final flush for any remaining buffered rows
    _flush_pending()

    # ── Write CSV/Excel outputs (for CLI use) ─────────────────────────────────
    out_df = pd.DataFrame(
        expanded_rows,
        columns=["make", "model", "year", "engine_capacity", "fuel", "source"],
    )
    out_df.to_csv(OUTPUT_CSV, index=False)
    out_df.to_excel(OUTPUT_EXCEL, index=False)
    unmatched_df = pd.DataFrame(
        [(m, mo, f) for (m, mo), f in unmatched_info.items()],
        columns=["make", "model", "fuel"],
    )
    unmatched_df.to_csv(UNMATCHED_CSV, index=False)

    n_enriched  = total_pairs - len(unmatched_info)
    n_not_found = len(unmatched_info)

    log("\n--- Year Enrichment Summary ---")
    log(f"Input pairs       : {total_pairs}")
    log(f"Enriched          : {n_enriched}")
    log(f"Not found         : {n_not_found}")
    log(f"Expanded rows     : {len(expanded_rows)}  (one per production year)")
    for src, cnt in sorted(src_counts.items(), key=lambda x: -x[1]):
        log(f"  {src}: {cnt} pairs")

    # ── Write unmatched to DB ─────────────────────────────────────────────────
    # Option 2: replace entire table on every run so only the latest run's
    # unmatched pairs are kept. No accumulation across runs.
    unmatched_models_list = [
        {"make": m, "model": mo, "fuel": f} for (m, mo), f in unmatched_info.items()
    ]
    if db is not None:
        from datetime import datetime, timezone as _tz
        from models import VehicleYearUnmatched
        now_utc = datetime.now(tz=_tz.utc)
        db.query(VehicleYearUnmatched).delete()          # clear ALL previous runs
        for (make_u, model_u), fuel_u in unmatched_info.items():
            db.add(VehicleYearUnmatched(
                run_id=run_id, make=make_u, model=model_u,
                fuel=fuel_u or None, recorded_at=now_utc,
            ))
        db.commit()
        log(f"  {len(unmatched_info)} unmatched pairs saved to vehicle_years_unmatched (run_id={run_id[:8]}...)")

    # staging was written incrementally above; build a summary dict for the return value
    staging_result = {"staged": total_staged, "skipped_unchanged": 0, "conflicts": 0} if db is not None else None

    provider_details = {
        src: {
            "hits":        src_counts.get(src, 0),
            "cache_hits":  cache_hit_counts.get(src, 0),
            "rate_limits": rate_limit_counter.get(src, 0),
        }
        for src in ("fueleconomy", "carapi", "wikipedia", "wikidata", "nhtsa")
    }

    return {
        "run_id":           run_id,
        "total_pairs":      total_pairs,
        "enriched":         n_enriched,
        "not_found":        n_not_found,
        "expanded_rows":    len(expanded_rows),
        "source_counts":    src_counts,
        "staging":          staging_result,
        "unmatched_models": unmatched_models_list,
        "provider_details": provider_details,
    }


# =========================
# CLI ENTRY POINT
# =========================
if __name__ == "__main__":
    result = main()
    print(f"\nDone. run_id={result['run_id']}")
