import os

import pandas as pd
import requests
import json
import re
import time
import urllib3

from rapidfuzz import process, fuzz

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =========================
# CONFIG
# =========================
INPUT_CSV             = "battery_lookup_dataset.csv"
OUTPUT_CSV            = "vehicle_years.csv"
OUTPUT_EXCEL          = "vehicle_years.xlsx"
UNMATCHED_CSV         = "unmatched_models.csv"
CACHE_FILE            = "cache/year_cache.json"
FUELECONOMY_CSV_URL   = "https://www.fueleconomy.gov/feg/epadata/vehicles.csv"
FUELECONOMY_CSV       = "cache/fueleconomy_vehicles.csv"
CURRENT_YEAR          = 2026
REQUEST_DELAY         = 1.0   # seconds between API calls
WIKI_SKIP_UNTIL       = 0     # epoch time — skip Wikipedia until this time (set after repeated 429s)
MATCH_SCORE_THRESHOLD = 45    # minimum fuzzy score (0-100) to accept a match

# ── Source URLs ────────────────────────────────────────────────
# 1. NHTSA VPIC — US government vehicle database (model lists)
NHTSA_MODELS_URL   = "https://vpic.nhtsa.dot.gov/api/vehicles/GetModelsForMakeYear/make/{make}/modelyear/{year}?format=json"
NHTSA_ALL_MODELS   = "https://vpic.nhtsa.dot.gov/api/vehicles/GetModelsForMake/{make}?format=json"
# 2. Wikipedia API — free, structured search + page extracts
WIKI_SEARCH_URL    = "https://en.wikipedia.org/w/api.php"
# 3. Wikidata SPARQL — structured production year data
WIKIDATA_SPARQL    = "https://query.wikidata.org/sparql"
# 4. CarAPI (free tier) — community car database
CARAPI_MAKES_URL   = "https://carapi.app/api/makes?verbose=yes&limit=50"
CARAPI_MODELS_URL  = "https://carapi.app/api/models?make={make}&verbose=yes&limit=200"
# 5. fueleconomy.gov — US DOE/EPA bulk CSV (1984–present, one row per vehicle-year)
# Downloaded once to FUELECONOMY_CSV and reused locally.

# Single HTTPS session — disables SSL verification to handle corporate proxy certificates
SESSION = requests.Session()
SESSION.verify = False
# Wikipedia requires a descriptive User-Agent with contact info to avoid throttling
SESSION.headers["User-Agent"] = "BatteryFinderBot/1.0 (battery-finder research; contact: battery-finder-bot@example.com)"

# =========================
# MAKE NAME MAP
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


def to_nhtsa_make(make):
    return MAKE_MAP.get(make.upper(), make.lower())


# =========================
# SOURCE 1 — NHTSA VPIC
# =========================
def fetch_nhtsa_models(make):
    nhtsa_make = to_nhtsa_make(make)
    url = NHTSA_ALL_MODELS.format(make=requests.utils.quote(nhtsa_make))
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json().get("Results", [])
    except Exception as e:
        print(f"    [NHTSA WARN] {make}: {e}")
    return []


# =========================
# SOURCE 2 — WIKIPEDIA API
# =========================
def get_years_from_wikipedia(make, model_name):
    global WIKI_SKIP_UNTIL
    if time.time() < WIKI_SKIP_UNTIL:
        remaining = int(WIKI_SKIP_UNTIL - time.time())
        print(f"    [Wiki] Skipping (cooling down for {remaining}s more)", flush=True)
        return None, None

    query = f"{make} {model_name} automobile"
    params = {"action": "query", "list": "search", "srsearch": query,
              "srlimit": 1, "format": "json", "utf8": 1}
    for attempt in range(3):
        try:
            r = SESSION.get(WIKI_SEARCH_URL, params=params, timeout=10)
            if r.status_code == 429:
                wait = 30 * (attempt + 1)  # 30s, 60s, 90s
                print(f"    [Wiki] 429 rate-limit, waiting {wait}s...", flush=True)
                time.sleep(wait)
                if attempt == 2:  # 3 strikes — pause Wikipedia for 5 minutes
                    WIKI_SKIP_UNTIL = time.time() + 300
                    print("    [Wiki] Repeated 429s — pausing Wikipedia for 5 minutes", flush=True)
                continue
            r.raise_for_status()
            results = r.json().get("query", {}).get("search", [])
            if not results:
                return None, None
            page_title = results[0]["title"]
            params2 = {"action": "query", "prop": "extracts", "exintro": True,
                       "titles": page_title, "format": "json", "utf8": 1}
            r2 = SESSION.get(WIKI_SEARCH_URL, params=params2, timeout=10)
            if r2.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"    [Wiki] 429 rate-limit, waiting {wait}s...", flush=True)
                time.sleep(wait)
                if attempt == 2:
                    WIKI_SKIP_UNTIL = time.time() + 300
                    print("    [Wiki] Repeated 429s — pausing Wikipedia for 5 minutes", flush=True)
                continue
            r2.raise_for_status()
            pages = r2.json().get("query", {}).get("pages", {})
            extract = next(iter(pages.values()), {}).get("extract", "")
            years = sorted(set(int(y) for y in re.findall(r'\b(19[5-9]\d|20[0-2]\d)\b', extract)))
            if not years:
                return None, None
            return years[0], years[-1]
        except Exception as e:
            print(f"    [Wiki WARN] {make} {model_name}: {e}")
            break
    return None, None


# =========================
# SOURCE 3 — WIKIDATA SPARQL
# =========================
def get_years_from_wikidata(make, model_name):
    query = f"""
    SELECT ?yearStart ?yearEnd WHERE {{
      ?car wdt:P31/wdt:P279* wd:Q3231690 .
      ?car rdfs:label ?label .
      FILTER(CONTAINS(LCASE(?label), "{model_name.lower()}"))
      FILTER(CONTAINS(LCASE(?label), "{make.split()[0].lower()}"))
      OPTIONAL {{ ?car wdt:P2047 ?yearStart . }}
      OPTIONAL {{ ?car wdt:P582 ?yearEnd . }}
      FILTER(LANG(?label) = "en")
    }} LIMIT 1
    """
    for attempt in range(3):
        try:
            resp = SESSION.get(
                WIKIDATA_SPARQL,
                params={"query": query, "format": "json"},
                timeout=15,
                headers={"Accept": "application/sparql-results+json"},
            )
            if resp.status_code == 429:
                wait = 15 * (attempt + 1)
                print(f"    [Wikidata] 429 rate-limit, waiting {wait}s...", flush=True)
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
            return None, None
        except Exception as e:
            print(f"    [Wikidata WARN] {make} {model_name}: {e}")
            break
    return None, None


# =========================
# SOURCE 4 — CARAPI.APP
# =========================
def fetch_carapi_models(make):
    nhtsa_make = to_nhtsa_make(make)
    url = CARAPI_MODELS_URL.format(make=requests.utils.quote(nhtsa_make))
    try:
        resp = SESSION.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            # CarAPI returns {data: [{name, year_first, year_last, ...}]}
            return data.get("data", [])
    except Exception as e:
        print(f"    [CarAPI WARN] {make}: {e}")
    return []


# =========================
# SOURCE 5 — FUELECONOMY.GOV (US DOE/EPA bulk CSV)
# =========================
# Maps dataset make names to fueleconomy.gov make names.
# None = make is not sold in the US market and will not be in the fueleconomy CSV.
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


def to_fe_make(make):
    """Return the fueleconomy.gov make name, or None if the make is not in the database."""
    upper = make.strip().upper()
    if upper in FE_MAKE_MAP:
        return FE_MAKE_MAP[upper]
    return make.strip().title()


def load_fueleconomy_data():
    """Download the fueleconomy.gov bulk CSV once, cache locally, and return a DataFrame."""
    if os.path.exists(FUELECONOMY_CSV):
        print(f"  [FE] Loading cached {FUELECONOMY_CSV}...")
    else:
        print("  [FE] Downloading fueleconomy.gov vehicles CSV...", end="", flush=True)
        try:
            resp = SESSION.get(FUELECONOMY_CSV_URL, timeout=120)
            resp.raise_for_status()
            with open(FUELECONOMY_CSV, "wb") as f:
                f.write(resp.content)
            print(f" done ({len(resp.content) // 1024} KB)")
        except Exception as e:
            print(f" FAILED: {e}")
            return pd.DataFrame(columns=["year", "make", "model"])
    try:
        return pd.read_csv(
            FUELECONOMY_CSV,
            usecols=["year", "make", "model"],
            dtype={"year": int, "make": str, "model": str},
        )
    except Exception as e:
        print(f"  [FE] Could not read CSV: {e}")
        return pd.DataFrame(columns=["year", "make", "model"])


def extract_base_model(make, model_name):
    """
    Strip the make-name prefix and trim-level noise, returning a short base model name
    suitable for matching against fueleconomy.gov (which only stores base model names).

    Examples:
      BMW  + "BMW 3 SERIES 320D X DRIVE M-SPORT"  -> "3 SERIES"
           + "ALPHARD G"                           -> "ALPHARD"
           + "ALLION A20 G-PLUS"                   -> "ALLION A20"
           + "86 GT LIMITED"                       -> "86"
    """
    name = model_name.strip()

    # Strip make name prefix if the model string starts with it (e.g. "BMW 3 Series...")
    for prefix in [make.strip(), make.split()[0].strip()]:
        if name.upper().startswith(prefix.upper()):
            name = name[len(prefix):].strip()
            break

    # Keep first 2 tokens — enough to identify a model, ignores trim/variant noise
    tokens = name.split()
    return " ".join(tokens[:2]) if tokens else model_name


def lookup_years_fueleconomy(make, model_name, fe_df):
    """
    Return a sorted list of exact production years from fueleconomy.gov, or None if not found.
    Covers US-market vehicles from 1984 to present with one record per model year.
    """
    if fe_df.empty:
        return None
    fe_make = to_fe_make(make)
    if fe_make is None:
        return None
    make_df = fe_df[fe_df["make"].str.strip().str.lower() == fe_make.lower()]
    if make_df.empty:
        return None
    unique_models = make_df["model"].dropna().unique().tolist()

    # Use a stripped base model name so trim-level noise doesn't break matching
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


# =========================
# MULTI-SOURCE YEAR LOOKUP
# =========================
def lookup_years(make, model_name, carapi_models, fe_df):
    """
    Try sources in priority order. Returns (years_list, source) where years_list is a
    sorted list of individual production years, or (None, None) if no match found.
    """

    # --- fueleconomy.gov (exact per-year data, US DOE/EPA — highest priority) ---
    years = lookup_years_fueleconomy(make, model_name, fe_df)
    if years:
        return years, "fueleconomy"

    # --- CarAPI (range-based — expand to explicit list) ---
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
                return list(range(yf, yt + 1)), "CarAPI"

    # --- Wikipedia (range-based) ---
    yf, yt = get_years_from_wikipedia(make, model_name)
    if yf:
        yt = min(yt, CURRENT_YEAR) if yt else CURRENT_YEAR
        return list(range(yf, yt + 1)), "Wikipedia"
    time.sleep(REQUEST_DELAY)

    # --- Wikidata SPARQL (range-based) ---
    yf, yt = get_years_from_wikidata(make, model_name)
    if yf:
        yt = min(yt, CURRENT_YEAR) if yt else CURRENT_YEAR
        return list(range(yf, yt + 1)), "Wikidata"
    time.sleep(REQUEST_DELAY)

    return None, None


# =========================
# FUZZY MATCH HELPER
# =========================
def best_model_match(our_model, nhtsa_models):
    if not nhtsa_models:
        return None, 0
    names = [m.get("Model_Name", "") for m in nhtsa_models]
    result = process.extractOne(our_model, names, scorer=fuzz.token_set_ratio)
    if result is None or result[1] < MATCH_SCORE_THRESHOLD:
        return None, 0
    return result[0], result[1]


# =========================
# LOAD CACHE
# =========================
try:
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache = json.load(f)
    print(f"Loaded cache with {len(cache)} top-level keys")
except FileNotFoundError:
    cache = {}
    print("No cache found - starting fresh")

for key in ("nhtsa", "carapi"):
    if key not in cache:
        cache[key] = {}

if "years" not in cache:
    cache["years"] = {}
print(f"Years cache: {len(cache['years'])} entries loaded")

# =========================
# LOAD DATASET
# =========================
df = pd.read_csv(INPUT_CSV)
unique_makes = df["make"].str.upper().unique().tolist()
total_makes  = len(unique_makes)

# =========================
# STAGE 1 — DOWNLOAD FUELECONOMY.GOV CSV
# =========================
print("\n[Stage 1/4] Loading fueleconomy.gov vehicle data...")
fe_df = load_fueleconomy_data()
print(f"  {len(fe_df):,} vehicle-year records loaded\n")

# =========================
# STAGE 2 — FETCH NHTSA MODEL LISTS
# =========================
print(f"[Stage 2/4] Fetching NHTSA model lists for {total_makes} makes...")

for make_idx, make in enumerate(unique_makes, start=1):
    if make in cache["nhtsa"]:
        print(f"  [{make_idx}/{total_makes}] [CACHED] {make}")
        continue
    print(f"  [{make_idx}/{total_makes}] [FETCH]  {make} ...", end="", flush=True)
    models = fetch_nhtsa_models(make)
    cache["nhtsa"][make] = models
    print(f" -> {len(models)} models")
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    print(f"           Waiting {REQUEST_DELAY}s...", flush=True)
    time.sleep(REQUEST_DELAY)

print("  Done.\n")

# =========================
# STAGE 3 — FETCH CARAPI MODEL LISTS
# =========================
print(f"[Stage 3/4] Fetching CarAPI model lists for {total_makes} makes...")

for make_idx, make in enumerate(unique_makes, start=1):
    if make in cache["carapi"]:
        print(f"  [{make_idx}/{total_makes}] [CACHED] {make}")
        continue
    print(f"  [{make_idx}/{total_makes}] [FETCH]  {make} ...", end="", flush=True)
    ca_models = fetch_carapi_models(make)
    cache["carapi"][make] = ca_models
    print(f" -> {len(ca_models)} models")
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    print(f"           Waiting {REQUEST_DELAY}s...", flush=True)
    time.sleep(REQUEST_DELAY)

print("  Done.\n")

# =========================
# STAGE 4 — MATCH + YEAR LOOKUP
# =========================
total        = len(df)
unique_pairs = df[["make", "model"]].drop_duplicates()
total_pairs  = len(unique_pairs)
print(f"[Stage 4/4] Looking up years for {total_pairs} unique make+model pairs...")

pairs_done  = {}
pairs_count = 0

for row_num, (_, row) in enumerate(df.iterrows(), start=1):
    make     = str(row.get("make", "")).strip().upper()
    model    = str(row.get("model", "")).strip()
    pair_key = f"{make}||{model}"

    if pair_key not in pairs_done:
        pairs_count += 1
        nhtsa_models = cache["nhtsa"].get(make, [])
        ca_models    = cache["carapi"].get(make, [])

        matched_name, score = best_model_match(model, nhtsa_models)

        # If full model name didn't match NHTSA, retry with the base model
        # (strips trim noise — e.g. "N-WGN CUSTOM G" → "N-WGN")
        if not matched_name:
            base_model = extract_base_model(make, model)
            if base_model.upper() != model.upper():
                matched_name, score = best_model_match(base_model, nhtsa_models)

        # Use the NHTSA-matched name if found; otherwise fall back to the
        # base model so Wikipedia/Wikidata get a clean search term too
        if matched_name:
            lookup_name = matched_name
        else:
            lookup_name = extract_base_model(make, model)

        year_key = f"{make}|{lookup_name}"
        if year_key in cache["years"]:
            years_list, src = cache["years"][year_key]
            print(f"  [{pairs_count}/{total_pairs}] [CACHED] {make} {lookup_name} ({src})")
        else:
            print(f"  [{pairs_count}/{total_pairs}] [LOOKUP] {make} {lookup_name} ...", end="", flush=True)
            years_list, src = lookup_years(make, lookup_name, ca_models, fe_df)
            cache["years"][year_key] = [years_list, src]
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f)
            status = f"{len(years_list)} years via {src}" if years_list else "not found"
            print(f" -> {status}")
            time.sleep(REQUEST_DELAY)

        pairs_done[pair_key] = (years_list, src)

    if row_num % 500 == 0 or row_num == total:
        matched_so_far = sum(1 for v in pairs_done.values() if v[0] is not None)
        pct = (row_num / total) * 100
        print(f"  Row {row_num}/{total} ({pct:.1f}%) | Pairs resolved: {matched_so_far}/{len(pairs_done)}")

# =========================
# BUILD OUTPUT — one row per production year
# =========================
# years_list contains the exact production years — no range expansion needed.
expanded_rows = []
unmatched_pairs = set()

for _, row in df.iterrows():
    make     = str(row.get("make", "")).strip().upper()
    model    = str(row.get("model", "")).strip()
    pair_key = f"{make}||{model}"
    years_list, _src = pairs_done.get(pair_key, (None, None))

    if years_list is None:
        unmatched_pairs.add((row.get("make"), row.get("model")))
        continue  # skip rows with no year data

    for yr in years_list:
        expanded_rows.append({
            "make":             row.get("make"),
            "model":            row.get("model"),
            "year":             yr,
            "engine_capacity":  row.get("engine_capacity"),
            "fuel":             row.get("fuel"),
        })

out_df = pd.DataFrame(expanded_rows, columns=["make", "model", "year", "engine_capacity", "fuel"])

# =========================
# REPORT
# =========================
total_in  = len(df)
total_out = len(out_df)
n_unmatched = len(unmatched_pairs)
print("\n--- Year Enrichment Summary ---")
print(f"Input rows        : {total_in}")
print(f"Rows with years   : {total_in - n_unmatched}")
print(f"Rows without years: {n_unmatched}  (excluded from output)")
print(f"Output rows       : {total_out}  (one per production year)")

src_counts = {}
for pair_key, (years_list, src) in pairs_done.items():
    if src:
        src_counts[src] = src_counts.get(src, 0) + 1
if src_counts:
    print("\nMatches by source:")
    for src, cnt in sorted(src_counts.items(), key=lambda x: -x[1]):
        print(f"  {src}: {cnt}")

# =========================
# SAVE OUTPUTS
# =========================
out_df.to_csv(OUTPUT_CSV, index=False)
print(f"\nCSV saved:   {OUTPUT_CSV}")

out_df.to_excel(OUTPUT_EXCEL, index=False)
print(f"Excel saved: {OUTPUT_EXCEL}")

unmatched_df = pd.DataFrame(list(unmatched_pairs), columns=["make", "model"])
unmatched_df.to_csv(UNMATCHED_CSV, index=False)
print(f"Unmatched:   {UNMATCHED_CSV}  ({len(unmatched_df)} unique pairs)")
