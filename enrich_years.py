import pandas as pd
import requests
import json
import re
import time

from rapidfuzz import process, fuzz

# =========================
# CONFIG
# =========================
INPUT_CSV          = "battery_lookup_dataset.csv"
EXCEL_SOURCE       = "New-CRSP---July-2025.xlsx"
OUTPUT_CSV         = "vehicle_years.csv"
OUTPUT_EXCEL       = "vehicle_years.xlsx"
UNMATCHED_CSV      = "unmatched_models.csv"
CACHE_FILE         = "year_cache.json"
REQUEST_DELAY      = 0.5   # seconds between API calls
MATCH_SCORE_THRESHOLD = 45 # minimum fuzzy score (0-100) to accept a match

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

HEADERS = {"User-Agent": "BatteryFinderBot/1.0 (research project)"}

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
        resp = requests.get(url, timeout=15, headers=HEADERS)
        resp.raise_for_status()
        return resp.json().get("Results", [])
    except Exception as e:
        print(f"    [NHTSA WARN] {make}: {e}")
    return []


# =========================
# SOURCE 2 — WIKIPEDIA API
# =========================
def get_years_from_wikipedia(make, model_name):
    query = f"{make} {model_name} automobile"
    params = {"action": "query", "list": "search", "srsearch": query,
              "srlimit": 1, "format": "json", "utf8": 1}
    try:
        r = requests.get(WIKI_SEARCH_URL, params=params, timeout=10, headers=HEADERS)
        r.raise_for_status()
        results = r.json().get("query", {}).get("search", [])
        if not results:
            return None, None
        page_title = results[0]["title"]
        params2 = {"action": "query", "prop": "extracts", "exintro": True,
                   "titles": page_title, "format": "json", "utf8": 1}
        r2 = requests.get(WIKI_SEARCH_URL, params=params2, timeout=10, headers=HEADERS)
        r2.raise_for_status()
        pages = r2.json().get("query", {}).get("pages", {})
        extract = next(iter(pages.values()), {}).get("extract", "")
        years = sorted(set(int(y) for y in re.findall(r'\b(19[5-9]\d|20[0-2]\d)\b', extract)))
        if not years:
            return None, None
        return years[0], years[-1]
    except Exception as e:
        print(f"    [Wiki WARN] {make} {model_name}: {e}")
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
    try:
        resp = requests.get(
            WIKIDATA_SPARQL,
            params={"query": query, "format": "json"},
            timeout=15,
            headers={**HEADERS, "Accept": "application/sparql-results+json"}
        )
        resp.raise_for_status()
        bindings = resp.json().get("results", {}).get("bindings", [])
        if bindings:
            yf = bindings[0].get("yearStart", {}).get("value")
            yt = bindings[0].get("yearEnd",   {}).get("value")
            yf = int(yf[:4]) if yf else None
            yt = int(yt[:4]) if yt else None
            if yf:
                return yf, yt
    except Exception as e:
        print(f"    [Wikidata WARN] {make} {model_name}: {e}")
    return None, None


# =========================
# SOURCE 4 — CARAPI.APP
# =========================
def fetch_carapi_models(make):
    nhtsa_make = to_nhtsa_make(make)
    url = CARAPI_MODELS_URL.format(make=requests.utils.quote(nhtsa_make))
    try:
        resp = requests.get(url, timeout=15, headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            # CarAPI returns {data: [{name, year_first, year_last, ...}]}
            return data.get("data", [])
    except Exception as e:
        print(f"    [CarAPI WARN] {make}: {e}")
    return []


# =========================
# MULTI-SOURCE YEAR LOOKUP
# =========================
def lookup_years(make, model_name, carapi_models):
    """Try multiple sources in order, return first successful (year_from, year_to, source)."""

    # --- CarAPI models list (already fetched per make) ---
    if carapi_models:
        ca_names = [m.get("name", "") for m in carapi_models]
        result = process.extractOne(model_name, ca_names, scorer=fuzz.token_set_ratio)
        if result and result[1] >= MATCH_SCORE_THRESHOLD:
            best = carapi_models[result[2]]
            yf = best.get("year_first") or best.get("year")
            yt = best.get("year_last")
            if yf:
                return int(yf), int(yt) if yt else None, "CarAPI"

    # --- Wikipedia ---
    yf, yt = get_years_from_wikipedia(make, model_name)
    if yf:
        return yf, yt, "Wikipedia"
    time.sleep(REQUEST_DELAY)

    # --- Wikidata SPARQL ---
    yf, yt = get_years_from_wikidata(make, model_name)
    if yf:
        return yf, yt, "Wikidata"
    time.sleep(REQUEST_DELAY)

    return None, None, None


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

for key in ("nhtsa", "carapi", "years"):
    if key not in cache:
        cache[key] = {}

# =========================
# LOAD DATASET
# =========================
df = pd.read_csv(INPUT_CSV)

# Merge model numbers from source Excel (model_number is the primary search key)
_xls = pd.read_excel(EXCEL_SOURCE)
_xls.columns = _xls.columns.str.strip().str.lower().str.replace(r'[\s\n]+', '_', regex=True)
if "model_number" in _xls.columns:
    _xls["make"]  = _xls["make"].astype(str).str.strip()
    _xls["model"] = _xls["model"].astype(str).str.strip()
    _model_nums = _xls[["make", "model", "model_number"]].drop_duplicates()
    df = df.merge(_model_nums, on=["make", "model"], how="left")
else:
    df["model_number"] = None

unique_makes = df["make"].str.upper().unique().tolist()
total_makes  = len(unique_makes)

# =========================
# STAGE 1 — FETCH NHTSA MODEL LISTS
# =========================
print(f"\n[Stage 1/3] Fetching NHTSA model lists for {total_makes} makes...")

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
# STAGE 2 — FETCH CARAPI MODEL LISTS
# =========================
print(f"[Stage 2/3] Fetching CarAPI model lists for {total_makes} makes...")

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
# STAGE 3 — MATCH + YEAR LOOKUP
# =========================
total        = len(df)
unique_pairs = df[["make", "model"]].drop_duplicates()
total_pairs  = len(unique_pairs)
print(f"[Stage 3/3] Looking up years for {total_pairs} unique make+model pairs...")

pairs_done  = {}
pairs_count = 0

for row_num, (_, row) in enumerate(df.iterrows(), start=1):
    make      = str(row.get("make", "")).strip().upper()
    model     = str(row.get("model", "")).strip()
    model_number = str(row.get("model_number", "")).strip()
    has_model_number = bool(model_number) and model_number.lower() not in ("nan", "")
    pair_key  = f"{make}||{model_number}" if has_model_number else f"{make}||{model}"

    if pair_key not in pairs_done:
        pairs_count += 1
        nhtsa_models = cache["nhtsa"].get(make, [])
        ca_models    = cache["carapi"].get(make, [])

        # NHTSA fuzzy match always uses the descriptive model name
        matched_name, score = best_model_match(model, nhtsa_models)

        # For Wikipedia/Wikidata queries: model_number first, fall back to matched/model name
        lookup_name = model_number if has_model_number else (matched_name if matched_name else model)

        year_key = f"{make}|{lookup_name}"
        if year_key in cache["years"]:
            yf, yt, src = cache["years"][year_key]
            print(f"  [{pairs_count}/{total_pairs}] [CACHED] {make} {lookup_name} ({src})")
        else:
            print(f"  [{pairs_count}/{total_pairs}] [LOOKUP] {make} {lookup_name} ...", end="", flush=True)
            yf, yt, src = lookup_years(make, lookup_name, ca_models)
            cache["years"][year_key] = [yf, yt, src]
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f)
            status = f"{yf}-{yt} via {src}" if yf else "not found"
            print(f" -> {status}")
            time.sleep(REQUEST_DELAY)

        pairs_done[pair_key] = (yf, yt, src)

    if row_num % 500 == 0 or row_num == total:
        matched_so_far = sum(1 for v in pairs_done.values() if v[0] is not None)
        pct = (row_num / total) * 100
        print(f"  Row {row_num}/{total} ({pct:.1f}%) | Pairs resolved: {matched_so_far}/{len(pairs_done)}")

# =========================
# BUILD OUTPUT DATAFRAME
# =========================
out_rows = []
for _, row in df.iterrows():
    make         = str(row.get("make", "")).strip().upper()
    model        = str(row.get("model", "")).strip()
    model_number = str(row.get("model_number", "")).strip()
    has_mn       = bool(model_number) and model_number.lower() not in ("nan", "")
    pair_key     = f"{make}||{model_number}" if has_mn else f"{make}||{model}"
    yf, yt, src  = pairs_done.get(pair_key, (None, None, None))
    out_rows.append({
        "make":         row.get("make"),
        "model":        row.get("model"),
        "model_number": model_number if has_mn else None,
        "year_from":    yf,
        "year_to":      yt,
        "year_source":  src,
    })

out_df = pd.DataFrame(out_rows)

# =========================
# REPORT
# =========================
filled     = out_df["year_from"].notna().sum()
not_filled = out_df["year_from"].isna().sum()
print("\n--- Year Enrichment Summary ---")
print(f"Total rows    : {total}")
print(f"Years matched : {filled}  ({filled/total*100:.1f}%)")
print(f"Not matched   : {not_filled}  ({not_filled/total*100:.1f}%)")

src_counts = out_df["year_source"].value_counts(dropna=True)
if len(src_counts):
    print("\nMatches by source:")
    for src, cnt in src_counts.items():
        print(f"  {src}: {cnt}")

# =========================
# SAVE OUTPUTS
# =========================
out_df.to_csv(OUTPUT_CSV, index=False)
print(f"\nCSV saved:   {OUTPUT_CSV}")

out_df.to_excel(OUTPUT_EXCEL, index=False)
print(f"Excel saved: {OUTPUT_EXCEL}")

unmatched = out_df[out_df["year_from"].isna()][["make", "model"]].drop_duplicates()
unmatched.to_csv(UNMATCHED_CSV, index=False)
print(f"Unmatched:   {UNMATCHED_CSV} ({len(unmatched)} unique pairs)")
