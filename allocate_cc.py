import json
import os
import re
import time
from collections import Counter
from typing import Optional, Tuple

import pandas as pd
import requests
import urllib3
from rapidfuzz import process, fuzz

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =========================
# CONFIG
# =========================
INPUT_CSV = "nts_vehicles_clean.csv"
OUTPUT_CSV = "nts_vehicles_with_cc.csv"
OUTPUT_EXCEL = "nts_vehicles_with_cc.xlsx"
UNMATCHED_CSV = "nts_unmatched_cc.csv"
CACHE_FILE = "cc_cache.json"

# fueleconomy.gov bulk CSV
FUELECONOMY_CSV_URL = "https://www.fueleconomy.gov/feg/epadata/vehicles.csv"
FUELECONOMY_CSV = "fueleconomy_vehicles.csv"

# Rate limiting / politeness
REQUEST_DELAY = 0.75
MATCH_SCORE_THRESHOLD = 55
YEAR_TOLERANCE = 0  # set to 1 to allow ±1-year matching

# Optional runtime controls (set as environment variables)
# - LIMIT_KEYS: only process the first N unique make+model+year keys (for dry runs)
# - ENABLE_CARQUERY / ENABLE_WIKIDATA / ENABLE_WIKIPEDIA: 0/1 toggles for fallbacks
LIMIT_KEYS = int(os.environ.get("LIMIT_KEYS", "0") or "0")
ENABLE_CARQUERY = os.environ.get("ENABLE_CARQUERY", "1") != "0"
ENABLE_WIKIDATA = os.environ.get("ENABLE_WIKIDATA", "1") != "0"
ENABLE_WIKIPEDIA = os.environ.get("ENABLE_WIKIPEDIA", "1") != "0"

# Wikipedia API
WIKI_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
WIKI_SKIP_UNTIL = 0

# Wikidata SPARQL
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

# CarQuery API (engine CC, trim info)
CARQUERY_TRIMS_URL = "https://www.carqueryapi.com/api/0.3/?cmd=getTrims&make={make}&model={model}&year={year}"

SESSION = requests.Session()
SESSION.verify = False
SESSION.headers["User-Agent"] = (
    "BatteryFinderBot/1.0 (allocate_cc; contact: battery-finder-bot@example.com)"
)

# -------------------------
# Make mapping (fueleconomy)
# -------------------------
# None = not in database / skip in FE stage
FE_MAKE_MAP = {
    "LANDROVER": "Land Rover",
    "LAND ROVER": "Land Rover",
    "MERCEDES": "Mercedes-Benz",
    "MERCEDES-BENZ": "Mercedes-Benz",
    "BRABUS": "Mercedes-Benz",
    "NISSAN DIESEL/UD": "Nissan",
    # These likely won't exist in FE
    "MITSUBISHI FUSO": None,
    "GREAT WALL": None,
    "SAIC MOTORS": None,
    "MARUTI SUZUKI": None,
    "IVECO DAILY": None,
    "PEUGEOT": "Peugeot",
    "CITROEN": "Citroen",
    "RENAULT": "Renault",
    "HAVAL": None,
}


def to_fe_make(make: str) -> Optional[str]:
    upper = (make or "").strip().upper()
    if upper in FE_MAKE_MAP:
        return FE_MAKE_MAP[upper]
    if not upper:
        return None
    return (make or "").strip().title()


_ws_re = re.compile(r"\s+")


def extract_base_model(make: str, model: str) -> str:
    """Strip make prefix and trim noise to improve cross-dataset matching."""
    name = (model or "").strip()

    for prefix in [(make or "").strip(), (make or "").split()[0].strip() if make else ""]:
        if prefix and name.upper().startswith(prefix.upper()):
            name = name[len(prefix):].strip()
            break

    name = _ws_re.sub(" ", name)
    tokens = name.split()
    # 2 tokens is a good balance; avoid losing identifiers like "ACE 125"
    return " ".join(tokens[:2]) if tokens else (model or "").strip()


def _choose_mode_int(values: list[int]) -> Optional[int]:
    if not values:
        return None
    counts = Counter(values)
    max_count = max(counts.values())
    tied = [v for v, c in counts.items() if c == max_count]
    return min(tied)  # deterministic tie-break


# =========================
# Cache
# =========================

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if isinstance(cache, dict):
                cache.setdefault("cc", {})
                return cache
        except Exception:
            pass
    return {"cc": {}}


def save_cache(cache: dict) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)


# =========================
# Source 1 — fueleconomy.gov
# =========================

def load_fueleconomy_data() -> pd.DataFrame:
    if os.path.exists(FUELECONOMY_CSV):
        print(f"  [FE] Loading cached {FUELECONOMY_CSV}...")
    else:
        print("  [FE] Downloading fueleconomy.gov vehicles CSV...", end="", flush=True)
        resp = SESSION.get(FUELECONOMY_CSV_URL, timeout=120)
        resp.raise_for_status()
        with open(FUELECONOMY_CSV, "wb") as f:
            f.write(resp.content)
        print(f" done ({len(resp.content) // 1024} KB)")

    usecols = ["year", "make", "model", "baseModel", "displ"]
    df = pd.read_csv(
        FUELECONOMY_CSV,
        usecols=usecols,
        dtype={"year": int, "make": str, "model": str, "baseModel": str},
        low_memory=False,
    )
    df["displ"] = pd.to_numeric(df["displ"], errors="coerce")
    # prefer baseModel if present
    df["_display_model"] = df["baseModel"].fillna("")
    df.loc[df["_display_model"].str.strip() == "", "_display_model"] = df["model"].fillna("")
    df["_display_model"] = df["_display_model"].astype(str)
    return df


def lookup_cc_fueleconomy(make: str, model: str, year: int, fe_df: pd.DataFrame) -> Optional[int]:
    if fe_df is None or fe_df.empty:
        return None

    fe_make = to_fe_make(make)
    if fe_make is None:
        return None

    # exact year first, then optional tolerance
    year_min = int(year) - int(YEAR_TOLERANCE)
    year_max = int(year) + int(YEAR_TOLERANCE)

    make_df = fe_df[
        (fe_df["make"].str.strip().str.lower() == fe_make.strip().lower())
        & (fe_df["year"] >= year_min)
        & (fe_df["year"] <= year_max)
    ]

    if make_df.empty:
        return None

    # if tolerance enabled, prefer closest year window
    if YEAR_TOLERANCE:
        make_df = make_df.assign(_yd=(make_df["year"] - int(year)).abs())
        min_yd = int(make_df["_yd"].min())
        make_df = make_df[make_df["_yd"] == min_yd]

    candidates = make_df["_display_model"].dropna().unique().tolist()
    if not candidates:
        return None

    query = extract_base_model(make, model)
    result = process.extractOne(query, candidates, scorer=fuzz.token_set_ratio)
    if result is None or result[1] < MATCH_SCORE_THRESHOLD:
        return None

    matched = result[0]
    matched_df = make_df[make_df["_display_model"] == matched]
    if matched_df.empty:
        return None

    displ = matched_df["displ"].dropna()
    displ = displ[displ > 0]  # ignore EV/unknown
    if displ.empty:
        return None

    cc_values = (displ * 1000).round().astype(int).tolist()
    # filter to plausible automotive cc range
    cc_values = [v for v in cc_values if 600 <= v <= 8000]
    return _choose_mode_int(cc_values)


# =========================
# Source 2 — CarQuery
# =========================

def _parse_carquery_json(text: str) -> Optional[dict]:
    t = (text or "").strip()
    if not t:
        return None
    # Sometimes returns: "var carquery = {...};"
    if t.startswith("var carquery"):
        eq = t.find("=")
        if eq != -1:
            t = t[eq + 1 :].strip()
        if t.endswith(";"):
            t = t[:-1]
    try:
        return json.loads(t)
    except Exception:
        return None


def lookup_cc_carquery(make: str, model: str, year: int) -> Optional[int]:
    make_q = (make or "").strip().lower()
    if not make_q:
        return None

    model_candidates = []
    base = extract_base_model(make, model)
    for m in [base, model]:
        m = (m or "").strip().lower()
        m = _ws_re.sub(" ", m)
        if m and m not in model_candidates:
            model_candidates.append(m)
        m2 = m.replace(" ", "-")
        if m2 and m2 not in model_candidates:
            model_candidates.append(m2)

    for idx, model_q in enumerate(model_candidates[:3], start=1):
        url = CARQUERY_TRIMS_URL.format(
            make=requests.utils.quote(make_q),
            model=requests.utils.quote(model_q),
            year=int(year),
        )
        try:
            resp = SESSION.get(url, timeout=20)
            if resp.status_code != 200:
                continue
            payload = _parse_carquery_json(resp.text)
            if not payload:
                continue
            trims = payload.get("Trims") or payload.get("trims") or []
            if not isinstance(trims, list) or not trims:
                continue

            cc_values: list[int] = []
            for tr in trims:
                if not isinstance(tr, dict):
                    continue
                raw_cc = tr.get("model_engine_cc") or tr.get("model_engine_cc")
                if raw_cc in (None, ""):
                    continue
                try:
                    cc = int(float(str(raw_cc).strip()))
                except Exception:
                    continue
                if 600 <= cc <= 8000:
                    cc_values.append(cc)

            chosen = _choose_mode_int(cc_values)
            if chosen is not None:
                return chosen
        except Exception:
            pass
        finally:
            # Be polite even when it fails
            if idx < len(model_candidates[:3]):
                time.sleep(REQUEST_DELAY)

    return None


# =========================
# Source 3 — Wikidata
# =========================

def lookup_cc_wikidata(make: str, model: str) -> Optional[int]:
    base_model = extract_base_model(make, model)
    make_token = (make or "").split()[0] if make else ""

    # P4218 = engine displacement
    query = f"""
    SELECT ?amount ?unitLabel WHERE {{
      ?item wdt:P31/wdt:P279* wd:Q3231690 .
      ?item rdfs:label ?label .
      FILTER(LANG(?label) = \"en\")
      FILTER(CONTAINS(LCASE(?label), \"{base_model.lower()}\"))
      FILTER(CONTAINS(LCASE(?label), \"{make_token.lower()}\"))
      ?item p:P4218/psv:P4218 ?dispNode .
      ?dispNode wikibase:quantityAmount ?amount .
      ?dispNode wikibase:quantityUnit ?unit .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language \"en\". }}
    }} LIMIT 5
    """

    try:
        resp = SESSION.get(
            WIKIDATA_SPARQL,
            params={"query": query, "format": "json"},
            timeout=25,
            headers={"Accept": "application/sparql-results+json"},
        )
        if resp.status_code != 200:
            return None
        bindings = resp.json().get("results", {}).get("bindings", [])
        if not bindings:
            return None

        cc_values: list[int] = []
        for b in bindings:
            amount_raw = b.get("amount", {}).get("value")
            unit_label = (b.get("unitLabel", {}) or {}).get("value", "")
            if amount_raw is None:
                continue
            try:
                amount = float(amount_raw)
            except Exception:
                continue

            unit_l = (unit_label or "").strip().lower()
            if "liter" in unit_l or unit_l == "l":
                cc = int(round(amount * 1000))
            elif "cubic centimet" in unit_l or "cc" in unit_l:
                cc = int(round(amount))
            else:
                # Unknown unit
                continue

            if 600 <= cc <= 8000:
                cc_values.append(cc)

        return _choose_mode_int(cc_values)
    except Exception:
        return None


# =========================
# Source 4 — Wikipedia
# =========================

def _extract_cc_candidates(text: str) -> list[int]:
    if not text:
        return []

    candidates: list[int] = []

    # e.g. "1798 cc", "998cc"
    for m in re.findall(r"\b(\d{3,4})\s*cc\b", text, flags=re.IGNORECASE):
        try:
            candidates.append(int(m))
        except Exception:
            pass

    # e.g. "1.8 L", "2.0-litre"
    for m in re.findall(r"\b(\d(?:\.\d)?)\s*(?:l|litre|liter)\b", text, flags=re.IGNORECASE):
        try:
            cc = int(round(float(m) * 1000))
            candidates.append(cc)
        except Exception:
            pass

    candidates = [c for c in candidates if 600 <= c <= 8000]
    return candidates


def lookup_cc_wikipedia(make: str, model: str) -> Optional[int]:
    global WIKI_SKIP_UNTIL
    if time.time() < WIKI_SKIP_UNTIL:
        return None

    query = f"{make} {model} engine displacement"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": 1,
        "format": "json",
        "utf8": 1,
    }

    for attempt in range(3):
        try:
            r = SESSION.get(WIKI_SEARCH_URL, params=params, timeout=15)
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                time.sleep(wait)
                if attempt == 2:
                    WIKI_SKIP_UNTIL = time.time() + 300
                continue
            r.raise_for_status()
            results = r.json().get("query", {}).get("search", [])
            if not results:
                return None

            title = results[0]["title"]
            params2 = {
                "action": "query",
                "prop": "extracts",
                "exintro": True,
                "titles": title,
                "format": "json",
                "utf8": 1,
            }
            r2 = SESSION.get(WIKI_SEARCH_URL, params=params2, timeout=15)
            if r2.status_code == 429:
                wait = 30 * (attempt + 1)
                time.sleep(wait)
                if attempt == 2:
                    WIKI_SKIP_UNTIL = time.time() + 300
                continue
            r2.raise_for_status()

            pages = r2.json().get("query", {}).get("pages", {})
            extract = next(iter(pages.values()), {}).get("extract", "")
            candidates = _extract_cc_candidates(extract)
            return _choose_mode_int(candidates)
        except Exception:
            break

    return None


# =========================
# Multi-source resolver
# =========================

def lookup_cc(make: str, model: str, year: int, fe_df: pd.DataFrame) -> Tuple[Optional[int], Optional[str]]:
    cc = lookup_cc_fueleconomy(make, model, year, fe_df)
    if cc is not None:
        return cc, "fueleconomy"

    if ENABLE_CARQUERY:
        time.sleep(REQUEST_DELAY)
        cc = lookup_cc_carquery(make, model, year)
        if cc is not None:
            return cc, "carquery"

    if ENABLE_WIKIDATA:
        time.sleep(REQUEST_DELAY)
        cc = lookup_cc_wikidata(make, model)
        if cc is not None:
            return cc, "wikidata"

    if ENABLE_WIKIPEDIA:
        time.sleep(REQUEST_DELAY)
        cc = lookup_cc_wikipedia(make, model)
        if cc is not None:
            return cc, "wikipedia"

    return None, None


def main() -> None:
    cache = load_cache()

    print("\n[Stage 1/2] Loading fueleconomy.gov vehicle data...")
    fe_df = load_fueleconomy_data()
    print(f"  {len(fe_df):,} records loaded")

    print("\n[Stage 2/2] Loading NTS cleaned dataset...")
    df = pd.read_csv(INPUT_CSV, dtype={"make": str, "model": str, "year": int})

    required = {"make", "model", "year"}
    missing = required - set(df.columns)
    if missing:
        raise Exception(f"Missing required columns in {INPUT_CSV}: {sorted(missing)}")

    unique_keys = df[["make", "model", "year"]].drop_duplicates().reset_index(drop=True)
    total_keys = len(unique_keys)
    print(f"  Unique make+model+year keys: {total_keys}")

    if LIMIT_KEYS and LIMIT_KEYS > 0:
        unique_keys = unique_keys.head(LIMIT_KEYS).reset_index(drop=True)
        print(f"  LIMIT_KEYS enabled: processing first {len(unique_keys)} keys")
        total_keys = len(unique_keys)

    results: dict[str, Tuple[Optional[int], Optional[str]]] = {}
    source_counts: Counter[str] = Counter()

    for idx, row in unique_keys.iterrows():
        make = str(row["make"]).strip().upper()
        model = str(row["model"]).strip()
        year = int(row["year"])
        key = f"{make}||{model}||{year}"

        if key in cache["cc"]:
            cc, src = cache["cc"][key]
            results[key] = (cc, src)
            if src:
                source_counts[src] += 1
            if (idx + 1) % 500 == 0 or (idx + 1) == total_keys:
                print(f"  [{idx+1}/{total_keys}] [CACHED] ...")
            continue

        cc, src = lookup_cc(make, model, year, fe_df)
        cache["cc"][key] = [cc, src]
        save_cache(cache)

        results[key] = (cc, src)
        if src:
            source_counts[src] += 1

        status = f"{cc}cc via {src}" if cc is not None else "not found"
        print(f"  [{idx+1}/{total_keys}] {make} {model} {year} -> {status}")

    # Build output
    engine_capacity = []
    sources = []
    for _, row in df.iterrows():
        make = str(row["make"]).strip().upper()
        model = str(row["model"]).strip()
        year = int(row["year"])
        key = f"{make}||{model}||{year}"
        cc, src = results.get(key, (None, None))
        engine_capacity.append(cc)
        sources.append(src)

    out_df = df.copy()
    out_df["engine_capacity"] = engine_capacity

    # Minimal output requested: do NOT include source column in final CSV.
    out_df = out_df[["make", "model", "year", "engine_capacity"]]

    unmatched_df = out_df[out_df["engine_capacity"].isna()][["make", "model", "year"]]

    print("\n--- Allocate CC Summary ---")
    matched = int(out_df["engine_capacity"].notna().sum())
    print(f"Total rows     : {len(out_df)}")
    print(f"CC matched     : {matched}")
    print(f"CC unmatched   : {len(out_df) - matched}")

    if source_counts:
        print("\nMatches by source:")
        for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
            print(f"  {src}: {cnt}")

    out_df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nCSV saved: {OUTPUT_CSV}")

    try:
        out_df.to_excel(OUTPUT_EXCEL, index=False)
        print(f"Excel saved: {OUTPUT_EXCEL}")
    except Exception as e:
        print(f"Excel output skipped: {e}")

    unmatched_df.to_csv(UNMATCHED_CSV, index=False)
    print(f"Unmatched saved: {UNMATCHED_CSV} ({len(unmatched_df)} rows)")


if __name__ == "__main__":
    main()
