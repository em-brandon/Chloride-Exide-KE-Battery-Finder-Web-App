"""
Vehicle Coverage Expansion Pipeline

Supplementary pipeline that expands vehicle_years beyond the CRSP battery catalogue.
Targets Kenya-relevant makes not well served by fueleconomy.gov (the CRSP pipeline's
primary source), using four data sources in priority order:

  1. NHTSA VPIC per-year   — exact make/model/year from US database (1981–present)
  2. CarQuery API           — global vehicle DB, covers non-US makes with year ranges
  3. cars-data.com          — scraper for Chinese & commercial vehicle makes
  4. car.info               — scraper for JDM and European model lineups

Results go to vehicle_years_staging (same staging → commit workflow as CRSP pipeline).
engine_capacity and fuel are best-effort filled from CarQuery's getTrims endpoint
(same CarQuery API used elsewhere in the codebase) for makes/models it recognizes;
they fall back to NULL when CarQuery has no coverage. Layer 3 (CC-based fallback)
only works for rows where a spec was found — Layers 1 & 2 work either way since
they only need make/model/year.

Run from CLI:
    python pipelines/vehicle_coverage_expansion.py [--makes toyota,nissan,...] [--years 1990-2026]

Run from admin UI:
    POST /api/admin/pipeline/vehicle-expansion/run
"""

import json
import os
import re
import threading
import time
import uuid
from collections import Counter

import requests
import urllib3
from rapidfuzz import fuzz, process

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =============================================================================
# CONFIG
# =============================================================================
CACHE_FILE     = "cache/expansion_cache.json"
CURRENT_YEAR   = 2026
YEAR_FROM      = 1981
REQUEST_DELAY  = 0.5   # seconds between API calls

NHTSA_YEAR_URL  = (
    "https://vpic.nhtsa.dot.gov/api/vehicles/"
    "GetModelsForMakeYear/make/{make}/modelYear/{year}?format=json"
)
CARQUERY_URL    = "https://www.carqueryapi.com/api/0.3/"
CARSDATA_URL    = "https://www.cars-data.com/en/{slug}-cars"
CARINFO_URL     = "https://www.car.info/en-gb/{slug}/"

SESSION = requests.Session()
SESSION.verify = False
SESSION.headers.update({
    "User-Agent": (
        "BatteryFinderBot/1.0 (battery-finder research; "
        "contact: battery-finder-bot@example.com)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})

# =============================================================================
# TARGET MAKES — curated for Kenya/East Africa market
# =============================================================================
# Maps our internal make name → (nhtsa_name, carquery_id, carsdata_slug, carinfo_slug)
# None means the source doesn't cover that make.
TARGET_MAKES: dict[str, dict] = {
    # Japanese (core Kenya market)
    "TOYOTA":          {"nhtsa": "Toyota",      "cq": "toyota",      "carsdata": "toyota",      "carinfo": "toyota"},
    "NISSAN":          {"nhtsa": "Nissan",       "cq": "nissan",      "carsdata": "nissan",      "carinfo": "nissan"},
    "HONDA":           {"nhtsa": "Honda",        "cq": "honda",       "carsdata": "honda",       "carinfo": "honda"},
    "MAZDA":           {"nhtsa": "Mazda",        "cq": "mazda",       "carsdata": "mazda",       "carinfo": "mazda"},
    "MITSUBISHI":      {"nhtsa": "Mitsubishi",   "cq": "mitsubishi",  "carsdata": "mitsubishi",  "carinfo": "mitsubishi"},
    "SUBARU":          {"nhtsa": "Subaru",       "cq": "subaru",      "carsdata": "subaru",      "carinfo": "subaru"},
    "DAIHATSU":        {"nhtsa": "Daihatsu",     "cq": "daihatsu",    "carsdata": "daihatsu",    "carinfo": "daihatsu"},
    "ISUZU":           {"nhtsa": "Isuzu",        "cq": "isuzu",       "carsdata": "isuzu",       "carinfo": "isuzu"},
    "SUZUKI":          {"nhtsa": "Suzuki",       "cq": "suzuki",      "carsdata": "suzuki",      "carinfo": "suzuki"},
    "LEXUS":           {"nhtsa": "Lexus",        "cq": "lexus",       "carsdata": "lexus",       "carinfo": "lexus"},
    "HINO":            {"nhtsa": "Hino",         "cq": None,          "carsdata": "hino",        "carinfo": "hino"},
    # European (poor fueleconomy.gov coverage)
    "PEUGEOT":         {"nhtsa": None,           "cq": "peugeot",     "carsdata": "peugeot",     "carinfo": "peugeot"},
    "RENAULT":         {"nhtsa": None,           "cq": "renault",     "carsdata": "renault",     "carinfo": "renault"},
    "CITROEN":         {"nhtsa": None,           "cq": "citroen",     "carsdata": "citroen",     "carinfo": "citroen"},
    "FIAT":            {"nhtsa": "Fiat",         "cq": "fiat",        "carsdata": "fiat",        "carinfo": "fiat"},
    "OPEL":            {"nhtsa": None,           "cq": "opel",        "carsdata": "opel",        "carinfo": "opel"},
    "VAUXHALL":        {"nhtsa": None,           "cq": "vauxhall",    "carsdata": "vauxhall",    "carinfo": "vauxhall"},
    "VOLVO":           {"nhtsa": "Volvo",        "cq": "volvo",       "carsdata": "volvo",       "carinfo": "volvo"},
    "SKODA":           {"nhtsa": None,           "cq": "skoda",       "carsdata": "skoda",       "carinfo": "skoda"},
    # German
    "MERCEDES":        {"nhtsa": "Mercedes-Benz","cq": "mercedes-benz","carsdata": "mercedes-benz","carinfo": "mercedes-benz"},
    "BMW":             {"nhtsa": "BMW",          "cq": "bmw",         "carsdata": "bmw",         "carinfo": "bmw"},
    "AUDI":            {"nhtsa": "Audi",         "cq": "audi",        "carsdata": "audi",        "carinfo": "audi"},
    "VOLKSWAGEN":      {"nhtsa": "Volkswagen",   "cq": "volkswagen",  "carsdata": "volkswagen",  "carinfo": "volkswagen"},
    # Korean
    "HYUNDAI":         {"nhtsa": "Hyundai",      "cq": "hyundai",     "carsdata": "hyundai",     "carinfo": "hyundai"},
    "KIA":             {"nhtsa": "Kia",          "cq": "kia",         "carsdata": "kia",         "carinfo": "kia"},
    # Chinese (growing East Africa segment)
    "HAVAL":           {"nhtsa": None,           "cq": None,          "carsdata": "haval",       "carinfo": "haval"},
    "GREAT WALL":      {"nhtsa": None,           "cq": "great-wall",  "carsdata": "great-wall",  "carinfo": "great-wall"},
    "CHERY":           {"nhtsa": None,           "cq": "chery",       "carsdata": "chery",       "carinfo": "chery"},
    "DONGFENG":        {"nhtsa": None,           "cq": None,          "carsdata": "dongfeng",    "carinfo": "dongfeng"},
    "FOTON":           {"nhtsa": None,           "cq": None,          "carsdata": "foton",       "carinfo": "foton"},
    "FAW":             {"nhtsa": None,           "cq": None,          "carsdata": "faw",         "carinfo": "faw"},
    "SAIC MOTORS":     {"nhtsa": None,           "cq": None,          "carsdata": "saic",        "carinfo": "saic"},
    # Commercial trucks
    "MAN":             {"nhtsa": None,           "cq": "man",         "carsdata": "man",         "carinfo": "man"},
    "SCANIA":          {"nhtsa": None,           "cq": None,          "carsdata": "scania",      "carinfo": "scania"},
    "IVECO DAILY":     {"nhtsa": None,           "cq": "iveco",       "carsdata": "iveco",       "carinfo": "iveco"},
    "MITSUBISHI FUSO": {"nhtsa": "Mitsubishi",   "cq": "mitsubishi",  "carsdata": "mitsubishi-fuso","carinfo": "mitsubishi-fuso"},
    "HINO":            {"nhtsa": "Hino",         "cq": None,          "carsdata": "hino",        "carinfo": "hino"},
    "MARUTI SUZUKI":   {"nhtsa": "Suzuki",       "cq": "suzuki",      "carsdata": "maruti-suzuki","carinfo": "maruti-suzuki"},
    "TATA":            {"nhtsa": None,           "cq": None,          "carsdata": "tata",        "carinfo": "tata"},
    "EICHER":          {"nhtsa": None,           "cq": None,          "carsdata": "eicher",      "carinfo": "eicher"},
    # Other
    "FORD":            {"nhtsa": "Ford",         "cq": "ford",        "carsdata": "ford",        "carinfo": "ford"},
    "JEEP":            {"nhtsa": "Jeep",         "cq": "jeep",        "carsdata": "jeep",        "carinfo": "jeep"},
    "LANDROVER":       {"nhtsa": "Land Rover",   "cq": "land-rover",  "carsdata": "land-rover",  "carinfo": "land-rover"},
    "CHEVROLET":       {"nhtsa": "Chevrolet",    "cq": "chevrolet",   "carsdata": "chevrolet",   "carinfo": "chevrolet"},
    "DODGE":           {"nhtsa": "Dodge",        "cq": "dodge",       "carsdata": "dodge",       "carinfo": "dodge"},
    "JAGUAR":          {"nhtsa": "Jaguar",       "cq": "jaguar",      "carsdata": "jaguar",      "carinfo": "jaguar"},
}

# =============================================================================
# SOURCE 1 — NHTSA VPIC per-year
# =============================================================================

def fetch_nhtsa_year(make_name: str, year: int, log=print) -> list[str]:
    """
    Returns list of model names for a given make and year.
    Uses GetModelsForMakeYear which gives exact per-year data (unlike GetModelsForMake).
    """
    url = NHTSA_YEAR_URL.format(
        make=requests.utils.quote(make_name),
        year=year,
    )
    try:
        resp = SESSION.get(url, timeout=12)
        resp.raise_for_status()
        results = resp.json().get("Results", [])
        return [r["Model_Name"] for r in results if r.get("Model_Name")]
    except Exception as e:
        log(f"    [NHTSA-year WARN] {make_name} {year}: {e}")
        return []


def collect_nhtsa_per_year(
    make: str,
    nhtsa_name: str,
    year_from: int,
    year_to: int,
    cache: dict,
    log=print,
    cancel_event: threading.Event = None,
) -> set[tuple[str, int]]:
    """
    Returns set of (model_name, year) tuples for a make across all target years.
    Results are cached in cache['nhtsa_year']['{make}:{year}'].
    """
    nhtsa_cache = cache.setdefault("nhtsa_year", {})
    pairs: set[tuple[str, int]] = set()

    for year in range(year_from, year_to + 1):
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Cancelled")
        cache_key = f"{make}:{year}"
        if cache_key in nhtsa_cache:
            models = nhtsa_cache[cache_key]
        else:
            models = fetch_nhtsa_year(nhtsa_name, year, log=log)
            nhtsa_cache[cache_key] = models
            _save_cache(cache)
            time.sleep(REQUEST_DELAY)

        for m in models:
            pairs.add((m.strip().upper(), year))

    return pairs


# =============================================================================
# SOURCE 2 — CarQuery API
# =============================================================================

def fetch_carquery_models(cq_make: str, cache: dict, log=print) -> list[dict]:
    """
    Fetches all model records for a make from CarQuery API.
    Returns list of dicts with keys: model_name, model_year (int).
    CarQuery returns JSONP; we strip the callback wrapper.
    Cached in cache['carquery'][cq_make].
    """
    cq_cache = cache.setdefault("carquery", {})
    if cq_make in cq_cache:
        return cq_cache[cq_make]

    try:
        resp = SESSION.get(
            CARQUERY_URL,
            params={"cmd": "getModels", "make": cq_make, "callback": "cq"},
            timeout=20,
        )
        resp.raise_for_status()
        # Strip JSONP: cq({...}) or cq ({...})
        text = resp.text.strip()
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            log(f"    [CarQuery WARN] {cq_make}: unexpected response format")
            cq_cache[cq_make] = []
            _save_cache(cache)
            return []
        data = json.loads(m.group())
        records = data.get("Models", [])
        log(f"    [CarQuery] {cq_make}: {len(records)} model records")
        cq_cache[cq_make] = records
        _save_cache(cache)
        time.sleep(REQUEST_DELAY)
        return records
    except Exception as e:
        log(f"    [CarQuery WARN] {cq_make}: {e}")
        cq_cache[cq_make] = []
        _save_cache(cache)
        return []


def carquery_to_pairs(make: str, records: list[dict]) -> set[tuple[str, int]]:
    """
    Converts CarQuery model records to (model_name_upper, year) pairs.
    CarQuery returns one record per trim per year; we use model_year field.
    """
    pairs: set[tuple[str, int]] = set()
    for r in records:
        model = (r.get("model_name") or "").strip()
        year_raw = r.get("model_year") or r.get("model_year_from") or ""
        if not model or not year_raw:
            continue
        try:
            year = int(str(year_raw)[:4])
        except ValueError:
            continue
        if YEAR_FROM <= year <= CURRENT_YEAR:
            pairs.add((model.upper(), year))
    return pairs


# =============================================================================
# ENGINE SPECS (CarQuery getTrims) — best-effort cc/fuel for new rows
# =============================================================================

def fetch_carquery_trims(cq_make: str, cq_model: str, cache: dict, log=print) -> list[dict]:
    """
    Fetches trims (with engine specs) for one make+model from CarQuery API.
    Same endpoint/params pattern as enrich_years.get_years_from_carquery(), just
    without a year filter so we get every year's trims in one call.
    Cached in cache['carquery_trims'][f"{cq_make}|{cq_model}"].
    """
    trims_cache = cache.setdefault("carquery_trims", {})
    key = f"{cq_make}|{cq_model}"
    if key in trims_cache:
        return trims_cache[key]

    try:
        resp = SESSION.get(
            CARQUERY_URL,
            params={"cmd": "getTrims", "make": cq_make, "model": cq_model},
            timeout=20,
        )
        resp.raise_for_status()
        body = resp.text.strip()
        if not body:
            trims_cache[key] = []
            _save_cache(cache)
            return []
        data = resp.json()
        trims = data.get("Trims", [])
        trims_cache[key] = trims
        _save_cache(cache)
        time.sleep(REQUEST_DELAY)
        return trims
    except Exception as e:
        log(f"    [CarQuery trims WARN] {cq_make} {cq_model}: {e}")
        trims_cache[key] = []
        _save_cache(cache)
        return []


def _normalize_carquery_fuel(raw: str | None) -> str | None:
    """
    Maps CarQuery's free-text model_engine_fuel (e.g. "Petrol - Regular unleaded
    (91)", "Diesel", "Hybrid (Electric/Gasoline)") onto the same fuel tokens
    already used elsewhere in vehicle_years (matcher._FUEL_MAP understands all
    of these). Returns None for unrecognized fuels (e.g. CNG, flex-fuel) rather
    than guessing.
    """
    if not raw:
        return None
    s = raw.strip().upper()
    if "HYBRID" in s:
        return "HYBRID"
    if "ELECTRIC" in s or s == "EV":
        return "ELECTRIC"
    if "DIESEL" in s:
        return "DIESEL"
    if "PETROL" in s or "GASOLINE" in s or "GAS" in s:
        return "PETROL"
    return None


def engine_specs_by_year(trims: list[dict]) -> dict[int, tuple[int | None, str | None]]:
    """
    Reduces a list of CarQuery trims to one (engine_cc, fuel) per model_year —
    picking the most common cc/fuel combination when a year has multiple trims
    (e.g. different engine options).
    """
    by_year: dict[int, Counter] = {}
    for t in trims:
        year_raw = t.get("model_year")
        if not year_raw:
            continue
        try:
            year = int(str(year_raw)[:4])
        except ValueError:
            continue

        cc = None
        cc_raw = t.get("model_engine_cc")
        if cc_raw:
            try:
                cc = int(float(cc_raw))
            except (TypeError, ValueError):
                cc = None

        fuel = _normalize_carquery_fuel(t.get("model_engine_fuel"))
        by_year.setdefault(year, Counter())[(cc, fuel)] += 1

    result: dict[int, tuple[int | None, str | None]] = {}
    for year, counter in by_year.items():
        (cc, fuel), _ = counter.most_common(1)[0]
        result[year] = (cc, fuel)
    return result


# =============================================================================
# SOURCE 3 — cars-data.com scraper
# =============================================================================

def _scrape_carsdata(slug: str, cache: dict, log=print) -> list[dict]:
    """
    Scrapes cars-data.com make page for model names and year ranges.
    Returns list of {model, year_from, year_to}.
    Cached in cache['carsdata'][slug].
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log("    [cars-data WARN] beautifulsoup4 not installed; skipping")
        return []

    carsdata_cache = cache.setdefault("carsdata", {})
    if slug in carsdata_cache:
        return carsdata_cache[slug]

    url = CARSDATA_URL.format(slug=slug)
    try:
        resp = SESSION.get(url, timeout=20, headers={"Accept": "text/html"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results = []

        # cars-data.com lists models in <a> tags with year text nearby.
        # Look for year pattern "YYYY" or "YYYY - YYYY" in proximity to model names.
        year_re = re.compile(r'\b(19[5-9]\d|20[0-2]\d)\b')

        for card in soup.select("div.car-list-card, div.list-item, article.car-item, li.model-item"):
            name_el = card.select_one("h2, h3, .model-name, .car-name, a[href]")
            if not name_el:
                continue
            model = name_el.get_text(strip=True)
            text_block = card.get_text(" ", strip=True)
            years_found = [int(y) for y in year_re.findall(text_block)
                           if YEAR_FROM <= int(y) <= CURRENT_YEAR]
            if not years_found:
                continue
            results.append({
                "model": model,
                "year_from": min(years_found),
                "year_to": max(years_found),
            })

        if not results:
            # Fallback: broader selector scan
            for link in soup.select("a[href*='specifications'], a[href*='/en/']"):
                text = link.get_text(strip=True)
                if not text or len(text) > 60:
                    continue
                years_found = [int(y) for y in year_re.findall(
                    link.parent.get_text(" ", strip=True) if link.parent else "")
                    if YEAR_FROM <= int(y) <= CURRENT_YEAR]
                if years_found:
                    results.append({
                        "model": text,
                        "year_from": min(years_found),
                        "year_to": max(years_found),
                    })

        log(f"    [cars-data] {slug}: {len(results)} models found")
        carsdata_cache[slug] = results
        _save_cache(cache)
        time.sleep(REQUEST_DELAY)
        return results
    except Exception as e:
        log(f"    [cars-data WARN] {slug}: {e}")
        carsdata_cache[slug] = []
        _save_cache(cache)
        return []


def carsdata_to_pairs(make: str, records: list[dict]) -> set[tuple[str, int]]:
    pairs: set[tuple[str, int]] = set()
    for r in records:
        model = (r.get("model") or "").strip().upper()
        yf = r.get("year_from") or YEAR_FROM
        yt = min(r.get("year_to") or CURRENT_YEAR, CURRENT_YEAR)
        if not model:
            continue
        for year in range(int(yf), int(yt) + 1):
            pairs.add((model, year))
    return pairs


# =============================================================================
# SOURCE 4 — car.info scraper
# =============================================================================

def _scrape_carinfo(slug: str, cache: dict, log=print) -> list[dict]:
    """
    Scrapes car.info make page for model names and year ranges.
    Returns list of {model, year_from, year_to}.
    Cached in cache['carinfo'][slug].
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log("    [car.info WARN] beautifulsoup4 not installed; skipping")
        return []

    carinfo_cache = cache.setdefault("carinfo", {})
    if slug in carinfo_cache:
        return carinfo_cache[slug]

    url = CARINFO_URL.format(slug=slug)
    try:
        resp = SESSION.get(url, timeout=20, headers={"Accept": "text/html"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results = []

        year_re = re.compile(r'\b(19[5-9]\d|20[0-2]\d)\b')

        # car.info uses model cards with year ranges like "1990 - 2005"
        for card in soup.select("div.model-card, div.car-model, article.model, li.car-item, div[class*='model']"):
            name_el = card.select_one("h2, h3, h4, .name, .title, a")
            if not name_el:
                continue
            model = name_el.get_text(strip=True)
            text_block = card.get_text(" ", strip=True)
            years_found = [int(y) for y in year_re.findall(text_block)
                           if YEAR_FROM <= int(y) <= CURRENT_YEAR]
            if not years_found:
                continue
            results.append({
                "model": model,
                "year_from": min(years_found),
                "year_to": max(years_found),
            })

        if not results:
            # Fallback: scan all text blocks near year patterns
            for el in soup.find_all(string=year_re):
                parent = el.find_parent(["li", "div", "article", "tr"])
                if not parent:
                    continue
                name_el = parent.select_one("a, h2, h3, h4, strong")
                if not name_el:
                    continue
                model = name_el.get_text(strip=True)
                if not model or len(model) > 60:
                    continue
                years_found = [int(y) for y in year_re.findall(parent.get_text(" "))
                               if YEAR_FROM <= int(y) <= CURRENT_YEAR]
                if years_found:
                    results.append({
                        "model": model,
                        "year_from": min(years_found),
                        "year_to": max(years_found),
                    })

        log(f"    [car.info] {slug}: {len(results)} models found")
        carinfo_cache[slug] = results
        _save_cache(cache)
        time.sleep(REQUEST_DELAY)
        return results
    except Exception as e:
        log(f"    [car.info WARN] {slug}: {e}")
        carinfo_cache[slug] = []
        _save_cache(cache)
        return []


def carinfo_to_pairs(make: str, records: list[dict]) -> set[tuple[str, int]]:
    return carsdata_to_pairs(make, records)  # identical structure


# =============================================================================
# CACHE HELPERS
# =============================================================================

def _load_cache() -> dict:
    os.makedirs("cache", exist_ok=True)
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save_cache(cache: dict) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)


# =============================================================================
# DEDUP AGAINST EXISTING vehicle_years
# =============================================================================

def _load_existing_pairs(db) -> set[tuple[str, str, int]]:
    """Returns set of (make_upper, model_upper, year) already in vehicle_years."""
    from sqlalchemy import text as sa_text
    rows = db.execute(
        sa_text("SELECT make, model, year FROM vehicle_years")
    ).fetchall()
    return {(r.make.upper(), r.model.upper(), r.year) for r in rows}


# =============================================================================
# MAIN
# =============================================================================

def main(
    run_id=None,
    db=None,
    target_makes: list[str] | None = None,
    year_from: int = YEAR_FROM,
    year_to: int = CURRENT_YEAR,
    log_callback=None,
    progress_callback=None,
    cancel_event: threading.Event = None,
    pause_event: threading.Event = None,
):
    """
    Run the vehicle coverage expansion pipeline.

    Parameters
    ----------
    run_id           : str   — UUID for this run (auto-generated if omitted)
    db               : SQLAlchemy Session — used to check existing rows + write staging
    target_makes     : list  — subset of TARGET_MAKES keys; defaults to all
    year_from / year_to : int — year range for NHTSA per-year queries
    log_callback     : callable(str)
    progress_callback: callable(processed, total, make, source)
    cancel_event     : threading.Event
    pause_event      : threading.Event

    Returns
    -------
    dict: {run_id, makes_processed, new_rows, staged, skipped, conflicts}
    """
    if run_id is None:
        run_id = str(uuid.uuid4())
    log = log_callback or print

    def _check():
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Cancelled")
        while pause_event and pause_event.is_set():
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Cancelled")
            time.sleep(0.5)

    makes_to_process = {
        k: v for k, v in TARGET_MAKES.items()
        if target_makes is None or k in target_makes
    }
    total_makes = len(makes_to_process)

    log(f"[Expansion] Starting run {run_id[:8]}...")
    log(f"[Expansion] {total_makes} makes targeted, years {year_from}–{year_to}")

    cache = _load_cache()

    # Load existing pairs for dedup
    existing_pairs: set[tuple[str, str, int]] = set()
    if db is not None:
        log("[Stage 0] Loading existing vehicle_years for deduplication...")
        existing_pairs = _load_existing_pairs(db)
        log(f"  {len(existing_pairs):,} existing (make, model, year) triples loaded")

    all_new_rows: list[dict] = []
    makes_done = 0

    for make, cfg in makes_to_process.items():
        _check()
        makes_done += 1
        make_pairs: set[tuple[str, int]] = set()  # (model_upper, year)
        source_tag = "nhtsa_peryear"

        log(f"\n[{makes_done}/{total_makes}] {make}")

        # --- Source 1: NHTSA per-year ---
        nhtsa_name = cfg.get("nhtsa")
        if nhtsa_name:
            log(f"  [NHTSA per-year] {nhtsa_name} {year_from}–{year_to}")
            try:
                nhtsa_pairs = collect_nhtsa_per_year(
                    make, nhtsa_name, year_from, year_to, cache, log=log,
                    cancel_event=cancel_event,
                )
                make_pairs |= nhtsa_pairs
                log(f"  [NHTSA per-year] {len(nhtsa_pairs)} (model, year) pairs")
            except InterruptedError:
                raise
            except Exception as e:
                log(f"  [NHTSA per-year WARN] {make}: {e}")

        # --- Source 2: CarQuery ---
        cq_name = cfg.get("cq")
        if cq_name:
            _check()
            log(f"  [CarQuery] {cq_name}")
            try:
                records = fetch_carquery_models(cq_name, cache, log=log)
                cq_pairs = carquery_to_pairs(make, records)
                new_from_cq = cq_pairs - make_pairs
                make_pairs |= cq_pairs
                log(f"  [CarQuery] {len(cq_pairs)} pairs, +{len(new_from_cq)} new")
                if not nhtsa_name and cq_pairs:
                    source_tag = "carquery"
            except Exception as e:
                log(f"  [CarQuery WARN] {make}: {e}")

        # --- Source 3: cars-data.com ---
        cd_slug = cfg.get("carsdata")
        if cd_slug:
            _check()
            log(f"  [cars-data] {cd_slug}")
            try:
                records = _scrape_carsdata(cd_slug, cache, log=log)
                cd_pairs = carsdata_to_pairs(make, records)
                new_from_cd = cd_pairs - make_pairs
                make_pairs |= cd_pairs
                log(f"  [cars-data] +{len(new_from_cd)} new pairs")
                if not nhtsa_name and not cq_name and cd_pairs:
                    source_tag = "carsdata"
            except Exception as e:
                log(f"  [cars-data WARN] {make}: {e}")

        # --- Source 4: car.info ---
        ci_slug = cfg.get("carinfo")
        if ci_slug:
            _check()
            log(f"  [car.info] {ci_slug}")
            try:
                records = _scrape_carinfo(ci_slug, cache, log=log)
                ci_pairs = carinfo_to_pairs(make, records)
                new_from_ci = ci_pairs - make_pairs
                make_pairs |= ci_pairs
                log(f"  [car.info] +{len(new_from_ci)} new pairs")
                if not nhtsa_name and not cq_name and not cd_slug and ci_pairs:
                    source_tag = "carinfo"
            except Exception as e:
                log(f"  [car.info WARN] {make}: {e}")

        # --- Engine specs (CarQuery getTrims), best-effort, for models with new rows ---
        model_specs: dict[str, dict[int, tuple]] = {}
        if cq_name:
            new_models = {m for (m, y) in make_pairs if (make, m, y) not in existing_pairs}
            for model_name in new_models:
                _check()
                trims = fetch_carquery_trims(cq_name, model_name, cache, log=log)
                if trims:
                    model_specs[model_name] = engine_specs_by_year(trims)
            if new_models:
                log(f"  [CarQuery specs] engine data found for {len(model_specs)}/{len(new_models)} new models")

        # --- Build rows, deduplicate against existing vehicle_years ---
        new_for_make = 0
        specs_filled = 0
        for (model, year) in make_pairs:
            if (make, model, year) not in existing_pairs:
                cc, fuel = model_specs.get(model, {}).get(year, (None, None))
                if cc is not None or fuel is not None:
                    specs_filled += 1
                all_new_rows.append({
                    "make":            make,
                    "model":           model,
                    "year":            year,
                    "engine_capacity": cc,
                    "fuel":            fuel,
                    "source":          source_tag,
                })
                existing_pairs.add((make, model, year))  # prevent intra-run dupes
                new_for_make += 1

        log(f"  → {new_for_make} new rows for {make} ({specs_filled} with engine specs; total so far: {len(all_new_rows):,})")

        if progress_callback:
            progress_callback(makes_done, total_makes, make, source_tag)

    log(f"\n[Expansion] Total new rows to stage: {len(all_new_rows):,}")

    # --- Write to staging ---
    staging_result = None
    if db is not None and all_new_rows:
        from pipelines.enrich_years import write_to_staging
        log(f"[Expansion] Writing {len(all_new_rows):,} rows to vehicle_years_staging...")
        staging_result = write_to_staging(db, run_id, all_new_rows)
        log(f"  Staged: {staging_result['staged']}, "
            f"Unchanged: {staging_result['skipped_unchanged']}, "
            f"Conflicts: {staging_result['conflicts']}")
    elif not all_new_rows:
        log("[Expansion] No new rows to stage — vehicle_years is already fully covered.")

    return {
        "run_id":         run_id,
        "makes_processed": makes_done,
        "new_rows":       len(all_new_rows),
        "staging":        staging_result,
    }


# =============================================================================
# CLI
# =============================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Vehicle coverage expansion pipeline")
    parser.add_argument("--makes",    help="Comma-separated makes to process (default: all)")
    parser.add_argument("--year-from", type=int, default=YEAR_FROM, dest="year_from")
    parser.add_argument("--year-to",   type=int, default=CURRENT_YEAR, dest="year_to")
    args = parser.parse_args()

    makes = [m.strip().upper() for m in args.makes.split(",")] if args.makes else None

    result = main(target_makes=makes, year_from=args.year_from, year_to=args.year_to)
    print(f"\nDone. run_id={result['run_id']}")
    print(f"  Makes processed : {result['makes_processed']}")
    print(f"  New rows        : {result['new_rows']:,}")
    if result["staging"]:
        s = result["staging"]
        print(f"  Staged          : {s['staged']:,}")
        print(f"  Skipped         : {s['skipped_unchanged']:,}")
        print(f"  Conflicts       : {s['conflicts']:,}")
