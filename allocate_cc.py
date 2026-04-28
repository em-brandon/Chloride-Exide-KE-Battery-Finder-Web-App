import json
import os
import re
import time
import base64
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
CACHE_VERSION = 5

# fueleconomy.gov bulk CSV
FUELECONOMY_CSV_URL = "https://www.fueleconomy.gov/feg/epadata/vehicles.csv"
FUELECONOMY_CSV = "fueleconomy_vehicles.csv"

# Rate limiting / politeness
REQUEST_DELAY = 0.75
MATCH_SCORE_THRESHOLD = 55
YEAR_TOLERANCE = 0  # set to 1 to allow ±1-year matching

# Optional runtime controls (set as environment variables)
# - LIMIT_KEYS: only process the first N unique make+model+year keys (for dry runs)
# - ENABLE_MODEL_TEXT: 0/1 toggle for parsing CC from the model string itself
# - ENABLE_CARAPI / ENABLE_CARQUERY / ENABLE_WIKIDATA / ENABLE_WIKIPEDIA: 0/1 toggles for fallbacks
LIMIT_KEYS = int(os.environ.get("LIMIT_KEYS", "0") or "0")
ENABLE_MODEL_TEXT = os.environ.get("ENABLE_MODEL_TEXT", "1") != "0"
ENABLE_CARAPI = os.environ.get("ENABLE_CARAPI", "1") != "0"
ENABLE_CARQUERY = os.environ.get("ENABLE_CARQUERY", "1") != "0"
ENABLE_WIKIDATA = os.environ.get("ENABLE_WIKIDATA", "1") != "0"
ENABLE_WIKIPEDIA = os.environ.get("ENABLE_WIKIPEDIA", "1") != "0"

# Wikipedia API
WIKI_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
WIKI_SKIP_UNTIL = 0

# Wikidata SPARQL
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

# CarAPI (engine size in liters via /api/engines/v2)
CARAPI_BASE_URL = "https://carapi.app"
CARAPI_AUTH_URL = f"{CARAPI_BASE_URL}/api/auth/login"
CARAPI_ENGINES_V2_URL = f"{CARAPI_BASE_URL}/api/engines/v2"
CARAPI_DEMO_MIN_YEAR = 2015
CARAPI_DEMO_MAX_YEAR = 2020

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


def _choose_consensus_cc(values: list[int], dominance: float = 0.6, min_samples: int = 3) -> Optional[int]:
    """Choose a CC value conservatively.

    Returns a value only when there is a single distinct value, or when a clear
    dominant mode exists (to reduce false positives).
    """
    values = [int(v) for v in values if isinstance(v, int) and 600 <= v <= 8000]
    if not values:
        return None

    uniq = sorted(set(values))
    if len(uniq) == 1:
        return uniq[0]

    if len(values) < min_samples:
        return None

    counts = Counter(values)
    (top_value, top_count) = counts.most_common(1)[0]
    if (top_count / len(values)) >= dominance:
        return int(top_value)
    return None


# =========================
# Cache
# =========================

def _cache_get_entry(cache: dict, key: str) -> Optional[dict]:
    cc_map = cache.get("cc")
    if not isinstance(cc_map, dict):
        return None

    entry = cc_map.get(key)
    if entry is None:
        return None

    # Back-compat: old format was [cc, src]
    if isinstance(entry, list):
        cc = entry[0] if len(entry) >= 1 else None
        src = entry[1] if len(entry) >= 2 else None
        new_entry = {"cc": cc, "src": src, "v": 1}
        cc_map[key] = new_entry
        return new_entry

    if isinstance(entry, dict):
        cc = entry.get("cc")
        src = entry.get("src")
        try:
            v = int(entry.get("v") or 1)
        except Exception:
            v = 1
        entry["cc"] = cc
        entry["src"] = src
        entry["v"] = v
        return entry

    return None


def _cache_entry_usable(entry: dict) -> bool:
    """Return True if we should trust the cache entry for this run.

    - If cc is known (non-None), always use it.
    - If cc is None (a previous 'not found'), only use it when it was computed
      with the current CACHE_VERSION.
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("cc") is not None:
        return True
    try:
        return int(entry.get("v") or 1) >= CACHE_VERSION
    except Exception:
        return False

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if isinstance(cache, dict):
                cache.setdefault("cc", {})
                # Store the current algorithm version for debugging; per-entry versions
                # are what control re-tries of prior negative cache results.
                cache.setdefault("version", 1)
                return cache
        except Exception:
            pass
    return {"cc": {}, "version": 1}


def save_cache(cache: dict) -> None:
    if isinstance(cache, dict):
        cache["version"] = CACHE_VERSION
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)


# =========================
# HTTP helpers
# =========================

def _sleep_backoff(attempt: int, base: float = 2.0, cap: float = 30.0) -> None:
    wait = min(cap, base * (2 ** attempt))
    time.sleep(wait)


def _safe_json(resp: requests.Response) -> Optional[dict]:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


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

    # RapidFuzz matching is case-sensitive unless we normalize.
    query = extract_base_model(make, model)
    result = process.extractOne(
        query,
        candidates,
        scorer=fuzz.token_set_ratio,
        processor=lambda s: str(s).lower(),
    )
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
# Source 2 — CarAPI
# =========================

_CARAPI_JWT: Optional[str] = None
_CARAPI_JWT_EXP: Optional[int] = None


def _jwt_exp_unverified(jwt_token: str) -> Optional[int]:
    """Extract exp claim from a JWT without verifying signature."""
    try:
        parts = (jwt_token or "").split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8")
        obj = json.loads(payload)
        exp = obj.get("exp")
        return int(exp) if exp is not None else None
    except Exception:
        return None


def _get_carapi_jwt() -> Optional[str]:
    global _CARAPI_JWT, _CARAPI_JWT_EXP

    # Highest priority: user-provided JWT
    env_jwt = (os.environ.get("CARAPI_JWT") or "").strip()
    if env_jwt:
        _CARAPI_JWT = env_jwt
        _CARAPI_JWT_EXP = _jwt_exp_unverified(env_jwt)
        return _CARAPI_JWT

    # Otherwise: login via api_token + api_secret
    api_token = (os.environ.get("CARAPI_API_TOKEN") or "").strip()
    api_secret = (os.environ.get("CARAPI_API_SECRET") or "").strip()
    if not api_token or not api_secret:
        return None

    now = int(time.time())
    if _CARAPI_JWT and _CARAPI_JWT_EXP and (_CARAPI_JWT_EXP - now) > 60:
        return _CARAPI_JWT

    try:
        r = SESSION.post(
            CARAPI_AUTH_URL,
            json={"api_token": api_token, "api_secret": api_secret},
            timeout=20,
        )
        if r.status_code != 200:
            return None
        token = (r.text or "").strip().strip('"')
        if not token:
            return None
        _CARAPI_JWT = token
        _CARAPI_JWT_EXP = _jwt_exp_unverified(token)
        return _CARAPI_JWT
    except Exception:
        return None


def lookup_cc_carapi(make: str, model: str, year: int) -> Optional[int]:
    if not ENABLE_CARAPI:
        return None

    jwt = _get_carapi_jwt()
    if jwt is None:
        # CarAPI demo dataset is limited; avoid wasting calls outside range.
        if not (CARAPI_DEMO_MIN_YEAR <= int(year) <= CARAPI_DEMO_MAX_YEAR):
            return None

    make_q = (make or "").strip().title()
    if not make_q:
        return None

    base_model = extract_base_model(make, model)
    model_candidates = []
    for m in [base_model, model]:
        m = (m or "").strip()
        m = _ws_re.sub(" ", m)
        if m and m not in model_candidates:
            model_candidates.append(m)

    headers = {}
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"

    for idx, model_q in enumerate(model_candidates[:2], start=1):
        params = {
            "year": int(year),
            "make": make_q,
            "model": model_q,
            "limit": 25,
        }

        for attempt in range(3):
            try:
                resp = SESSION.get(CARAPI_ENGINES_V2_URL, params=params, headers=headers, timeout=20)
                if resp.status_code == 429:
                    _sleep_backoff(attempt, base=2.0, cap=20.0)
                    continue
                if resp.status_code != 200:
                    break

                payload = _safe_json(resp)
                if not payload:
                    break

                data = payload.get("data")
                if not isinstance(data, list) or not data:
                    break

                cc_values: list[int] = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    size_l = item.get("size")
                    if size_l in (None, ""):
                        continue
                    try:
                        size_l_f = float(size_l)
                    except Exception:
                        continue
                    if size_l_f <= 0:
                        continue
                    cc = int(round(size_l_f * 1000))
                    if 600 <= cc <= 8000:
                        cc_values.append(cc)

                chosen = _choose_consensus_cc(cc_values)
                if chosen is not None:
                    return chosen
                break
            except Exception:
                break
            finally:
                time.sleep(REQUEST_DELAY)

        if idx < len(model_candidates[:2]):
            time.sleep(REQUEST_DELAY)

    return None


# =========================
# Source 3 — CarQuery
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
# Source 4 — Wikidata
# =========================

def _sparql_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', "\\\"").replace("\n", " ")


def _parse_quantity_to_cc(amount: float, unit_label: str) -> Optional[int]:
    unit_l = (unit_label or "").strip().lower()
    if "liter" in unit_l or unit_l == "l" or "litre" in unit_l:
        cc = int(round(amount * 1000))
    elif "cubic centimet" in unit_l or "cubic centimeter" in unit_l or "cc" in unit_l or "cm3" in unit_l:
        cc = int(round(amount))
    elif "cubic inch" in unit_l or "cu in" in unit_l:
        cc = int(round(amount * 16.387064))
    else:
        return None
    return cc if 600 <= cc <= 8000 else None


def lookup_cc_wikidata(make: str, model: str) -> Optional[int]:
    base_model = extract_base_model(make, model)
    search = _sparql_escape(f"{make} {base_model}".strip())

    # P4218 = engine displacement
    # Use mwapi EntitySearch for more robust matching than simple label CONTAINS.
    query = f"""
    SELECT ?amount ?unitLabel WHERE {{
      SERVICE wikibase:mwapi {{
        bd:serviceParam wikibase:endpoint "www.wikidata.org" ;
                        wikibase:api "EntitySearch" ;
                        mwapi:search "{search}" ;
                        mwapi:language "en" ;
                        mwapi:limit 5 .
        ?item wikibase:apiOutputItem mwapi:item .
      }}
      ?item p:P4218/psv:P4218 ?dispNode .
      ?dispNode wikibase:quantityAmount ?amount .
      ?dispNode wikibase:quantityUnit ?unit .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }} LIMIT 10
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
        payload = _safe_json(resp)
        if not payload:
            return None

        bindings = payload.get("results", {}).get("bindings", [])
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

            cc = _parse_quantity_to_cc(amount, unit_label)
            if cc is not None:
                cc_values.append(cc)

        return _choose_consensus_cc(cc_values, dominance=0.6, min_samples=2) or _choose_mode_int(cc_values)
    except Exception:
        return None


# =========================
# Source 5 — Wikipedia
# =========================

def _extract_cc_candidates(text: str) -> list[int]:
    if not text:
        return []

    candidates: list[int] = []

    # e.g. "1798 cc", "998cc", "1,998 cc"
    for m in re.findall(r"\b(\d{1,2}[,\s]?\d{3})\s*(?:cc|cm3|cm³)\b", text, flags=re.IGNORECASE):
        try:
            candidates.append(int(str(m).replace(",", "").replace(" ", "")))
        except Exception:
            pass

    # e.g. "1.8 L", "2.0-litre", "2 L"
    for m in re.findall(r"\b(\d(?:\.\d{1,2})?)\s*(?:l|litre|liter)\b", text, flags=re.IGNORECASE):
        try:
            cc = int(round(float(m) * 1000))
            candidates.append(cc)
        except Exception:
            pass

    # MediaWiki convert templates e.g. {{convert|1998|cc|L|abbr=on}}
    for m in re.findall(r"\{\{\s*convert\s*\|\s*([0-9]+(?:\.[0-9]+)?)\s*\|\s*([A-Za-z0-9³]+)", text, flags=re.IGNORECASE):
        num_s, unit_s = m
        try:
            num = float(num_s)
        except Exception:
            continue
        unit_l = (unit_s or "").strip().lower()
        if unit_l in {"l", "litre", "liter"}:
            candidates.append(int(round(num * 1000)))
        elif unit_l in {"cc", "cm3", "cm³"}:
            candidates.append(int(round(num)))

    candidates = [c for c in candidates if 600 <= c <= 8000]
    return candidates


_MODEL_LITERS_INLINE_RE = re.compile(
    r"\b([0-9](?:\.[0-9]{1,2})?)\s*([A-Za-z]{1,6}[0-9]{0,2})\b"
)


def lookup_cc_from_model_text(model: str) -> Optional[int]:
    """Best-effort extraction from the NTS model string.

    Many rows embed engine size in the model/variant text (e.g. '2.8GD6').
    This is intentionally conservative: we only accept values that look like
    real displacement (600–8000cc).
    """
    if not ENABLE_MODEL_TEXT:
        return None

    s = (model or "").strip()
    if not s:
        return None

    candidates: list[int] = []
    # Explicit units first
    candidates.extend(_extract_cc_candidates(s))

    # Inline liters without an explicit unit, e.g. '2.8GD6'
    for num_s, suffix in _MODEL_LITERS_INLINE_RE.findall(s):
        try:
            liters = float(num_s)
        except Exception:
            continue
        if not (0.6 <= liters <= 8.0):
            continue
        # Avoid accidentally treating wheel sizes / ratios as displacement.
        suf = (suffix or "").lower()
        if suf in {"x", "xr", "x4"}:
            continue
        candidates.append(int(round(liters * 1000)))

    candidates = [c for c in candidates if 600 <= c <= 8000]
    return _choose_consensus_cc(candidates, dominance=0.6, min_samples=2) or _choose_mode_int(candidates)


def _wikipedia_search_title(make: str, model: str) -> Optional[str]:
    query = f"{make} {model}".strip()
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": 1,
        "format": "json",
        "utf8": 1,
    }
    try:
        r = SESSION.get(WIKI_SEARCH_URL, params=params, timeout=15)
        if r.status_code != 200:
            return None
        results = (r.json().get("query", {}) or {}).get("search", [])
        if not results:
            return None
        return results[0].get("title")
    except Exception:
        return None


def _wikipedia_fetch_wikitext(title: str) -> Optional[str]:
    params = {
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "titles": title,
        "format": "json",
        "formatversion": 2,
        "utf8": 1,
    }
    try:
        r = SESSION.get(WIKI_SEARCH_URL, params=params, timeout=20)
        if r.status_code != 200:
            return None
        payload = r.json()
        pages = (payload.get("query", {}) or {}).get("pages", [])
        if not pages:
            return None
        revs = pages[0].get("revisions") or []
        if not revs:
            return None
        slots = (revs[0].get("slots") or {}).get("main") or {}
        content = slots.get("content")
        return content if isinstance(content, str) else None
    except Exception:
        return None


def lookup_cc_wikipedia(make: str, model: str) -> Optional[int]:
    global WIKI_SKIP_UNTIL
    if time.time() < WIKI_SKIP_UNTIL:
        return None

    for attempt in range(3):
        try:
            title = _wikipedia_search_title(make, model)
            if not title:
                return None

            wikitext = _wikipedia_fetch_wikitext(title)
            if not wikitext:
                return None

            # Prefer infobox-like fields that tend to include engine displacement.
            engine_lines: list[str] = []
            for m in re.finditer(
                r"(?im)^\|\s*(?:engine|engines|displacement|engine_size|engine_capacity)\s*=\s*(.+)$",
                wikitext,
            ):
                engine_lines.append(m.group(1).strip())

            # If we didn't find explicit fields, fall back to scanning a smaller window around "Infobox".
            snippet = "\n".join(engine_lines)
            if not snippet:
                infobox_idx = wikitext.lower().find("{{infobox")
                if infobox_idx != -1:
                    snippet = wikitext[infobox_idx : infobox_idx + 20000]

            candidates = _extract_cc_candidates(snippet)
            chosen = _choose_consensus_cc(candidates)
            if chosen is not None:
                return chosen

            # If ambiguous, do not guess.
            return None
        except Exception:
            if attempt == 2:
                return None
            _sleep_backoff(attempt, base=2.0, cap=10.0)

    return None


# =========================
# Multi-source resolver
# =========================

def lookup_cc(make: str, model: str, year: int, fe_df: pd.DataFrame) -> Tuple[Optional[int], Optional[str]]:
    cc = lookup_cc_fueleconomy(make, model, year, fe_df)
    if cc is not None:
        return cc, "fueleconomy"

    cc = lookup_cc_from_model_text(model)
    if cc is not None:
        return cc, "model_text"

    if ENABLE_CARAPI:
        time.sleep(REQUEST_DELAY)
        cc = lookup_cc_carapi(make, model, year)
        if cc is not None:
            return cc, "carapi"

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
    dirty_cache = False

    for i, row in enumerate(unique_keys.to_dict("records"), start=1):
        make = str(row["make"]).strip().upper()
        model = str(row["model"]).strip()
        year = int(row["year"])
        key = f"{make}||{model}||{year}"

        entry = _cache_get_entry(cache, key)
        if entry is not None and _cache_entry_usable(entry):
            cc = entry.get("cc")
            src = entry.get("src")
            results[key] = (cc, src)
            if src:
                source_counts[src] += 1
            if (i % 500) == 0 or i == total_keys:
                print(f"  [{i}/{total_keys}] [CACHED] ...")
            continue

        cc, src = lookup_cc(make, model, year, fe_df)
        cache["cc"][key] = {"cc": cc, "src": src, "v": CACHE_VERSION}
        dirty_cache = True
        if (i % 50) == 0 or i == total_keys:
            save_cache(cache)
            dirty_cache = False

        results[key] = (cc, src)
        if src:
            source_counts[src] += 1

        status = f"{cc}cc via {src}" if cc is not None else "not found"
        print(f"  [{i}/{total_keys}] {make} {model} {year} -> {status}")

    if dirty_cache:
        save_cache(cache)

    # Build output
    engine_capacity = []
    sources = []
    for _, row in df.iterrows():
        make = str(row["make"]).strip().upper()
        model = str(row["model"]).strip()
        year = int(row["year"])
        key = f"{make}||{model}||{year}"
        if key in results:
            cc, src = results[key]
        else:
            entry = _cache_get_entry(cache, key)
            if entry is not None and _cache_entry_usable(entry):
                cc = entry.get("cc")
                src = entry.get("src")
            else:
                cc, src = (None, None)
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
