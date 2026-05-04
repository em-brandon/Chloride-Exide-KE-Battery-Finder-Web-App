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
OUTPUT_CSV = "nts_vehicles_enriched.csv"
OUTPUT_EXCEL = "nts_vehicles_enriched.xlsx"
UNMATCHED_CSV = "nts_unmatched_enriched.csv"
CACHE_FILE = "enrichment_cache.json"
CACHE_VERSION = 1

# fueleconomy.gov bulk CSV
FUELECONOMY_CSV_URL = "https://www.fueleconomy.gov/feg/epadata/vehicles.csv"
FUELECONOMY_CSV = "fueleconomy_vehicles.csv"

# Rate limiting / politeness
REQUEST_DELAY = 0.75
MATCH_SCORE_THRESHOLD = 55
YEAR_TOLERANCE = 1  # allow ±1-year matching to catch more vehicles

# Optional runtime controls (set as environment variables)
LIMIT_KEYS = int(os.environ.get("LIMIT_KEYS", "0") or "0")
ENABLE_MODEL_TEXT = os.environ.get("ENABLE_MODEL_TEXT", "1") != "0"
ENABLE_CARAPI = os.environ.get("ENABLE_CARAPI", "1") != "0"
ENABLE_CARQUERY = os.environ.get("ENABLE_CARQUERY", "1") != "0"
ENABLE_WIKIDATA = os.environ.get("ENABLE_WIKIDATA", "1") != "0"
ENABLE_WIKIPEDIA = os.environ.get("ENABLE_WIKIPEDIA", "1") != "0"

# Wikipedia / Wikidata
WIKI_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
WIKI_SKIP_UNTIL = 0
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

# CarAPI
CARAPI_BASE_URL = "https://carapi.app"
CARAPI_AUTH_URL = f"{CARAPI_BASE_URL}/api/auth/login"
CARAPI_ENGINES_V2_URL = f"{CARAPI_BASE_URL}/api/engines/v2"
CARAPI_DEMO_MIN_YEAR = 2015
CARAPI_DEMO_MAX_YEAR = 2020

# CarQuery
CARQUERY_TRIMS_URL = "https://www.carqueryapi.com/api/0.3/?cmd=getTrims&make={make}&model={model}&year={year}"

SESSION = requests.Session()
SESSION.verify = False
SESSION.headers["User-Agent"] = (
    "BatteryFinderBot/1.0 (allocate_cc_fuel; contact: battery-finder-bot@example.com)"
)

# -------------------------
# Make mapping (fueleconomy.gov)
# None = not present in FE database, skip FE stage for this make
# -------------------------
FE_MAKE_MAP = {
    "LANDROVER": "Land Rover",
    "LAND ROVER": "Land Rover",
    "MERCEDES": "Mercedes-Benz",
    "MERCEDES-BENZ": "Mercedes-Benz",
    "BRABUS": "Mercedes-Benz",
    "NISSAN DIESEL/UD": "Nissan",
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

# -------------------------
# Fuel type keyword patterns
# Order matters: more specific patterns before general ones.
# -------------------------
_FUEL_PATTERNS: list[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b(PHEV|PLUG[\s\-]?IN[\s\-]?HYBRID)\b", re.I), "PLUG-IN HYBRID"),
    (re.compile(r"\b(HEV|HYBRID)\b", re.I), "HYBRID"),
    (re.compile(r"\b(BEV|FULL[\s\-]?ELECTRIC|ALL[\s\-]?ELECTRIC)\b", re.I), "ELECTRIC"),
    (re.compile(r"\b(EV|ELECTRIC)\b", re.I), "ELECTRIC"),
    (re.compile(r"\bDIESEL\b", re.I), "DIESEL"),
    (re.compile(r"\b(PETROL|GASOLINE|BENZINE|BENZIN)\b", re.I), "PETROL"),
    (re.compile(r"\b(CNG|COMPRESSED[\s\-]?NATURAL[\s\-]?GAS|NATURAL[\s\-]?GAS)\b", re.I), "CNG"),
    (re.compile(r"\b(LPG|LIQUEFIED[\s\-]?PETROLEUM|AUTOGAS|PROPANE)\b", re.I), "LPG"),
    (re.compile(r"\b(HYDROGEN|FUEL[\s\-]?CELL|FCV)\b", re.I), "HYDROGEN"),
]

# Regex to find fuel-related infobox fields in Wikipedia wikitext
_WIKI_FUEL_FIELDS_RE = re.compile(
    r"(?im)^\|\s*(?:fuel[_\s]?type|fuel[_\s]?system|fuel|engine[_\s]?fuel)\s*=\s*(.+)$"
)


# =========================
# Fuel normalization
# =========================

def normalize_fuel(raw: str) -> Optional[str]:
    """Map any raw fuel string from any source to a canonical label."""
    if not raw:
        return None
    s = raw.strip().upper()

    # Exact atvType tokens from fueleconomy.gov
    if s == "EV":
        return "ELECTRIC"
    if s == "PLUG-IN HYBRID":
        return "PLUG-IN HYBRID"
    if s == "HYBRID":
        return "HYBRID"
    if s in ("FFV",):
        return "PETROL"  # flex-fuel vehicle, primarily gasoline
    if s == "CNG":
        return "CNG"
    if s in ("FCV", "EFCV"):
        return "HYDROGEN"

    # Substring checks on the normalised string
    if "PLUG-IN" in s or "PLUG IN" in s or "PHEV" in s:
        return "PLUG-IN HYBRID"
    if "HYBRID" in s or "HEV" in s:
        return "HYBRID"
    if "ELECTRIC" in s or "BEV" in s:
        return "ELECTRIC"
    if "DIESEL" in s:
        return "DIESEL"
    if any(x in s for x in ("GASOLINE", "PETROL", "REGULAR", "PREMIUM", "MIDGRADE", "UNLEADED", "BENZIN")):
        return "PETROL"
    if "NATURAL GAS" in s or "CNG" in s or "COMPRESSED GAS" in s:
        return "CNG"
    if "LPG" in s or "LIQUEFIED PETROLEUM" in s or "PROPANE" in s or "AUTOGAS" in s:
        return "LPG"
    if "HYDROGEN" in s or "FUEL CELL" in s or "FCV" in s:
        return "HYDROGEN"

    # Fall back to regex patterns (handles mixed case, hyphens, spaces)
    for pat, label in _FUEL_PATTERNS:
        if pat.search(raw):
            return label
    return None


def _fe_row_to_fuel(fueltype1: str, atvtype: str) -> Optional[str]:
    """Derive canonical fuel type from fueleconomy.gov row fields."""
    at = (atvtype or "").strip()
    ft = (fueltype1 or "").strip()
    # atvType is more specific (distinguishes EV vs Hybrid vs Plug-in)
    if at:
        result = normalize_fuel(at)
        if result:
            return result
    if ft:
        return normalize_fuel(ft)
    return None


# =========================
# String utilities
# =========================

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
    return " ".join(tokens[:2]) if tokens else (model or "").strip()


# =========================
# CC consensus helpers
# =========================

def _choose_mode_int(values: list[int]) -> Optional[int]:
    if not values:
        return None
    counts = Counter(values)
    max_count = max(counts.values())
    tied = [v for v, c in counts.items() if c == max_count]
    return min(tied)  # deterministic tie-break


def _choose_consensus_cc(
    values: list[int], dominance: float = 0.6, min_samples: int = 3
) -> Optional[int]:
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

    # Back-compat: old list format [cc, src]
    if isinstance(entry, list):
        cc = entry[0] if len(entry) >= 1 else None
        src = entry[1] if len(entry) >= 2 else None
        new_entry = {"cc": cc, "cc_src": src, "fuel": None, "fuel_src": None, "v": 1}
        cc_map[key] = new_entry
        return new_entry

    if isinstance(entry, dict):
        # Migrate old {cc, src, v} format
        if "src" in entry and "cc_src" not in entry:
            entry["cc_src"] = entry.pop("src", None)
        entry.setdefault("cc", None)
        entry.setdefault("cc_src", None)
        entry.setdefault("fuel", None)
        entry.setdefault("fuel_src", None)
        try:
            entry["v"] = int(entry.get("v") or 1)
        except Exception:
            entry["v"] = 1
        return entry
    return None


def _cache_entry_usable(entry: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    # Both values known — always use regardless of version
    if entry.get("cc") is not None and entry.get("fuel") is not None:
        return True
    # Partial or no result — only reuse if from current cache version
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
# Source 1 — fueleconomy.gov (CC + Fuel)
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

    usecols = ["year", "make", "model", "baseModel", "displ", "fuelType1", "atvType"]
    df = pd.read_csv(
        FUELECONOMY_CSV,
        usecols=usecols,
        dtype={"year": int, "make": str, "model": str, "baseModel": str},
        low_memory=False,
    )
    df["displ"] = pd.to_numeric(df["displ"], errors="coerce")
    df["fuelType1"] = df["fuelType1"].fillna("").astype(str)
    df["atvType"] = df["atvType"].fillna("").astype(str)
    # Prefer baseModel for matching if present
    df["_display_model"] = df["baseModel"].fillna("")
    df.loc[df["_display_model"].str.strip() == "", "_display_model"] = df["model"].fillna("")
    df["_display_model"] = df["_display_model"].astype(str)
    return df


def lookup_cc_fuel_fueleconomy(
    make: str, model: str, year: int, fe_df: pd.DataFrame
) -> Tuple[Optional[int], Optional[str]]:
    """Return (engine_cc, fuel_type) from a fueleconomy.gov fuzzy match."""
    if fe_df is None or fe_df.empty:
        return None, None

    fe_make = to_fe_make(make)
    if fe_make is None:
        return None, None

    year_min = int(year) - int(YEAR_TOLERANCE)
    year_max = int(year) + int(YEAR_TOLERANCE)

    make_df = fe_df[
        (fe_df["make"].str.strip().str.lower() == fe_make.strip().lower())
        & (fe_df["year"] >= year_min)
        & (fe_df["year"] <= year_max)
    ]
    if make_df.empty:
        return None, None

    # Prefer closest year when tolerance is active
    if YEAR_TOLERANCE:
        make_df = make_df.assign(_yd=(make_df["year"] - int(year)).abs())
        min_yd = int(make_df["_yd"].min())
        make_df = make_df[make_df["_yd"] == min_yd]

    candidates = make_df["_display_model"].dropna().unique().tolist()
    if not candidates:
        return None, None

    query = extract_base_model(make, model)
    result = process.extractOne(
        query,
        candidates,
        scorer=fuzz.token_set_ratio,
        processor=lambda s: str(s).lower(),
    )
    if result is None or result[1] < MATCH_SCORE_THRESHOLD:
        return None, None

    matched = result[0]
    matched_df = make_df[make_df["_display_model"] == matched]
    if matched_df.empty:
        return None, None

    # --- CC ---
    displ = matched_df["displ"].dropna()
    displ = displ[displ > 0]
    cc_result: Optional[int] = None
    if not displ.empty:
        cc_values = (displ * 1000).round().astype(int).tolist()
        cc_values = [v for v in cc_values if 600 <= v <= 8000]
        cc_result = _choose_mode_int(cc_values)

    # --- Fuel type: majority vote across matched rows ---
    fuel_votes: list[str] = []
    for _, row in matched_df.iterrows():
        f = _fe_row_to_fuel(str(row.get("fuelType1", "")), str(row.get("atvType", "")))
        if f:
            fuel_votes.append(f)
    fuel_result: Optional[str] = Counter(fuel_votes).most_common(1)[0][0] if fuel_votes else None

    return cc_result, fuel_result


# =========================
# Source: Model text (CC + Fuel)
# =========================

_MODEL_LITERS_INLINE_RE = re.compile(
    r"\b([0-9](?:\.[0-9]{1,2})?)\s*([A-Za-z]{1,6}[0-9]{0,2})\b"
)


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

    # e.g. "1.8 L", "2.0-litre"
    for m in re.findall(r"\b(\d(?:\.\d{1,2})?)\s*(?:l|litre|liter)\b", text, flags=re.IGNORECASE):
        try:
            candidates.append(int(round(float(m) * 1000)))
        except Exception:
            pass

    # MediaWiki convert templates e.g. {{convert|1998|cc|L|abbr=on}}
    for m in re.findall(
        r"\{\{\s*convert\s*\|\s*([0-9]+(?:\.[0-9]+)?)\s*\|\s*([A-Za-z0-9³]+)",
        text,
        flags=re.IGNORECASE,
    ):
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

    return [c for c in candidates if 600 <= c <= 8000]


def lookup_cc_from_model_text(model: str) -> Optional[int]:
    if not ENABLE_MODEL_TEXT:
        return None
    s = (model or "").strip()
    if not s:
        return None

    candidates: list[int] = []
    candidates.extend(_extract_cc_candidates(s))

    # Inline liters without explicit unit, e.g. "2.8GD6", "2.0TDI".
    # Be conservative: avoid mis-parsing drivetrain badges like "4MATIC" / "4WD".
    _bad_suffixes = {
        "matic", "quattro", "xdrive", "motion",
        "awd", "fwd", "rwd", "wd",
        "4wd", "4x4",
        "cvt",
        "sport", "plus", "premium",
    }
    for num_s, suffix in _MODEL_LITERS_INLINE_RE.findall(s):
        try:
            liters = float(num_s)
        except Exception:
            continue
        if not (0.6 <= liters <= 8.0):
            continue
        suf = (suffix or "").lower()
        if suf in {"x", "xr", "x4"}:
            continue
        if suf in _bad_suffixes:
            continue

        # Require either a decimal point ("2.0T") OR digits in suffix ("2.8GD6").
        # This filters common false positives like "4MATIC" and "4WD".
        if ("." not in num_s) and (not any(ch.isdigit() for ch in suf)):
            continue
        candidates.append(int(round(liters * 1000)))

    candidates = [c for c in candidates if 600 <= c <= 8000]
    return _choose_consensus_cc(candidates, dominance=0.6, min_samples=2) or _choose_mode_int(candidates)


def lookup_fuel_from_model_text(model: str) -> Optional[str]:
    if not ENABLE_MODEL_TEXT:
        return None
    s = (model or "").strip()
    if not s:
        return None
    for pattern, label in _FUEL_PATTERNS:
        if pattern.search(s):
            return label
    return None


# =========================
# Source 2 — CarAPI (CC + Fuel)
# =========================

_CARAPI_JWT: Optional[str] = None
_CARAPI_JWT_EXP: Optional[int] = None


def _jwt_exp_unverified(jwt_token: str) -> Optional[int]:
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

    env_jwt = (os.environ.get("CARAPI_JWT") or "").strip()
    if env_jwt:
        _CARAPI_JWT = env_jwt
        _CARAPI_JWT_EXP = _jwt_exp_unverified(env_jwt)
        return _CARAPI_JWT

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


def lookup_cc_fuel_carapi(
    make: str, model: str, year: int
) -> Tuple[Optional[int], Optional[str]]:
    if not ENABLE_CARAPI:
        return None, None

    jwt = _get_carapi_jwt()
    if jwt is None:
        if not (CARAPI_DEMO_MIN_YEAR <= int(year) <= CARAPI_DEMO_MAX_YEAR):
            return None, None

    make_q = (make or "").strip().title()
    if not make_q:
        return None, None

    base_model = extract_base_model(make, model)
    model_candidates: list[str] = []
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
                resp = SESSION.get(
                    CARAPI_ENGINES_V2_URL, params=params, headers=headers, timeout=20
                )
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
                fuel_votes: list[str] = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    # CC
                    size_l = item.get("size")
                    if size_l not in (None, ""):
                        try:
                            size_l_f = float(size_l)
                            if size_l_f > 0:
                                cc = int(round(size_l_f * 1000))
                                if 600 <= cc <= 8000:
                                    cc_values.append(cc)
                        except Exception:
                            pass
                    # Fuel type — CarAPI may return it under different field names
                    for field in ("fuel_type", "fuelType", "fuel"):
                        raw_fuel = item.get(field)
                        if raw_fuel:
                            f = normalize_fuel(str(raw_fuel))
                            if f:
                                fuel_votes.append(f)
                            break

                cc_chosen = _choose_consensus_cc(cc_values)
                fuel_chosen = Counter(fuel_votes).most_common(1)[0][0] if fuel_votes else None

                if cc_chosen is not None or fuel_chosen is not None:
                    return cc_chosen, fuel_chosen
                break
            except Exception:
                break
            finally:
                time.sleep(REQUEST_DELAY)

        if idx < len(model_candidates[:2]):
            time.sleep(REQUEST_DELAY)

    return None, None


# =========================
# Source 3 — CarQuery (CC + Fuel)
# =========================

def _parse_carquery_json(text: str) -> Optional[dict]:
    t = (text or "").strip()
    if not t:
        return None
    if t.startswith("var carquery"):
        eq = t.find("=")
        if eq != -1:
            t = t[eq + 1:].strip()
        if t.endswith(";"):
            t = t[:-1]
    try:
        return json.loads(t)
    except Exception:
        return None


def lookup_cc_fuel_carquery(
    make: str, model: str, year: int
) -> Tuple[Optional[int], Optional[str]]:
    make_q = (make or "").strip().lower()
    if not make_q:
        return None, None

    model_candidates: list[str] = []
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
            fuel_votes: list[str] = []
            for tr in trims:
                if not isinstance(tr, dict):
                    continue
                # CC
                raw_cc = tr.get("model_engine_cc")
                if raw_cc not in (None, ""):
                    try:
                        cc = int(float(str(raw_cc).strip()))
                        if 600 <= cc <= 8000:
                            cc_values.append(cc)
                    except Exception:
                        pass
                # Fuel — CarQuery uses model_engine_fuel
                raw_fuel = tr.get("model_engine_fuel") or tr.get("model_fuel_cap")
                if raw_fuel:
                    f = normalize_fuel(str(raw_fuel))
                    if f:
                        fuel_votes.append(f)

            cc_chosen = _choose_mode_int(cc_values)
            fuel_chosen = Counter(fuel_votes).most_common(1)[0][0] if fuel_votes else None

            if cc_chosen is not None or fuel_chosen is not None:
                return cc_chosen, fuel_chosen
        except Exception:
            pass
        finally:
            if idx < len(model_candidates[:3]):
                time.sleep(REQUEST_DELAY)

    return None, None


# =========================
# Source 4 — Wikidata (CC only)
# =========================

def _sparql_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _parse_quantity_to_cc(amount: float, unit_label: str) -> Optional[int]:
    unit_l = (unit_label or "").strip().lower()
    if "liter" in unit_l or unit_l == "l" or "litre" in unit_l:
        cc = int(round(amount * 1000))
    elif "cubic centimet" in unit_l or "cc" in unit_l or "cm3" in unit_l:
        cc = int(round(amount))
    elif "cubic inch" in unit_l or "cu in" in unit_l:
        cc = int(round(amount * 16.387064))
    else:
        return None
    return cc if 600 <= cc <= 8000 else None


def lookup_cc_wikidata(make: str, model: str) -> Optional[int]:
    if not ENABLE_WIKIDATA:
        return None

    base_model = extract_base_model(make, model)
    search = _sparql_escape(f"{make} {base_model}".strip())

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
# Source 5 — Wikipedia (CC + Fuel)
# =========================

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


def lookup_cc_fuel_wikipedia(
    make: str, model: str
) -> Tuple[Optional[int], Optional[str]]:
    global WIKI_SKIP_UNTIL
    if not ENABLE_WIKIPEDIA:
        return None, None
    if time.time() < WIKI_SKIP_UNTIL:
        return None, None

    for attempt in range(3):
        try:
            title = _wikipedia_search_title(make, model)
            if not title:
                return None, None

            wikitext = _wikipedia_fetch_wikitext(title)
            if not wikitext:
                return None, None

            # --- CC: prefer explicit engine/displacement infobox fields ---
            engine_lines: list[str] = []
            for m in re.finditer(
                r"(?im)^\|\s*(?:engine|engines|displacement|engine_size|engine_capacity)\s*=\s*(.+)$",
                wikitext,
            ):
                engine_lines.append(m.group(1).strip())

            snippet = "\n".join(engine_lines)
            if not snippet:
                infobox_idx = wikitext.lower().find("{{infobox")
                if infobox_idx != -1:
                    snippet = wikitext[infobox_idx:infobox_idx + 20000]

            cc_candidates = _extract_cc_candidates(snippet)
            cc_chosen = _choose_consensus_cc(cc_candidates)

            # --- Fuel: explicit fuel infobox fields ---
            fuel_chosen: Optional[str] = None
            for m in _WIKI_FUEL_FIELDS_RE.finditer(wikitext):
                raw = m.group(1).strip()
                # Strip wiki markup links [[text|display]] and templates {{...}}
                raw = re.sub(r"\[\[([^\]|]+\|)?([^\]]+)\]\]", r"\2", raw)
                raw = re.sub(r"\{\{[^}]+\}\}", "", raw).strip()
                f = normalize_fuel(raw)
                if f:
                    fuel_chosen = f
                    break

            # Fallback: keyword scan over infobox snippet
            if fuel_chosen is None and snippet:
                for pat, label in _FUEL_PATTERNS:
                    if pat.search(snippet):
                        fuel_chosen = label
                        break

            return cc_chosen, fuel_chosen
        except Exception:
            if attempt == 2:
                return None, None
            _sleep_backoff(attempt, base=2.0, cap=10.0)

    return None, None


# =========================
# Multi-source resolver
# =========================

def lookup_cc_fuel(
    make: str, model: str, year: int, fe_df: pd.DataFrame
) -> Tuple[Optional[int], Optional[str], Optional[str], Optional[str]]:
    """Resolve engine CC and fuel type for a vehicle using all available sources.

    Returns (cc, cc_src, fuel, fuel_src).
    Sources are tried independently for cc and fuel so a partial result
    from one source does not block the other value from being found elsewhere.
    """
    cc: Optional[int] = None
    cc_src: Optional[str] = None
    fuel: Optional[str] = None
    fuel_src: Optional[str] = None

    # --- Step 1: Model text (free, no network) ---
    # Treat as a low-confidence fallback so it doesn't block better sources.
    model_text_cc: Optional[int] = None
    model_text_fuel: Optional[str] = None
    if ENABLE_MODEL_TEXT:
        model_text_cc = lookup_cc_from_model_text(model)
        model_text_fuel = lookup_fuel_from_model_text(model)

    # --- Step 2: fueleconomy.gov (single fuzzy match returns both) ---
    fe_cc, fe_fuel = lookup_cc_fuel_fueleconomy(make, model, year, fe_df)
    if fe_cc is not None and cc is None:
        cc = fe_cc
        cc_src = "fueleconomy"
    if fe_fuel is not None and fuel is None:
        fuel = fe_fuel
        fuel_src = "fueleconomy"

    if cc is not None and fuel is not None:
        return cc, cc_src, fuel, fuel_src

    # --- Step 3: CarAPI ---
    if ENABLE_CARAPI and (cc is None or fuel is None):
        time.sleep(REQUEST_DELAY)
        api_cc, api_fuel = lookup_cc_fuel_carapi(make, model, year)
        if api_cc is not None and cc is None:
            cc = api_cc
            cc_src = "carapi"
        if api_fuel is not None and fuel is None:
            fuel = api_fuel
            fuel_src = "carapi"

    if cc is not None and fuel is not None:
        return cc, cc_src, fuel, fuel_src

    # --- Step 4: CarQuery ---
    if ENABLE_CARQUERY and (cc is None or fuel is None):
        time.sleep(REQUEST_DELAY)
        cq_cc, cq_fuel = lookup_cc_fuel_carquery(make, model, year)
        if cq_cc is not None and cc is None:
            cc = cq_cc
            cc_src = "carquery"
        if cq_fuel is not None and fuel is None:
            fuel = cq_fuel
            fuel_src = "carquery"

    if cc is not None and fuel is not None:
        return cc, cc_src, fuel, fuel_src

    # --- Step 5: Wikidata (CC only) ---
    if ENABLE_WIKIDATA and cc is None:
        time.sleep(REQUEST_DELAY)
        wd_cc = lookup_cc_wikidata(make, model)
        if wd_cc is not None:
            cc = wd_cc
            cc_src = "wikidata"

    # --- Step 6: Wikipedia (CC + fuel) ---
    if ENABLE_WIKIPEDIA and (cc is None or fuel is None):
        time.sleep(REQUEST_DELAY)
        wiki_cc, wiki_fuel = lookup_cc_fuel_wikipedia(make, model)
        if wiki_cc is not None and cc is None:
            cc = wiki_cc
            cc_src = "wikipedia"
        if wiki_fuel is not None and fuel is None:
            fuel = wiki_fuel
            fuel_src = "wikipedia"

    # Final fallback: model-text inference (very low confidence)
    if cc is None and model_text_cc is not None:
        cc = model_text_cc
        cc_src = "model_text"
    if fuel is None and model_text_fuel is not None:
        fuel = model_text_fuel
        fuel_src = "model_text"

    return cc, cc_src, fuel, fuel_src


# =========================
# Main
# =========================

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

    results: dict[str, tuple] = {}
    cc_source_counts: Counter[str] = Counter()
    fuel_source_counts: Counter[str] = Counter()
    dirty_cache = False

    for i, row in enumerate(unique_keys.to_dict("records"), start=1):
        make = str(row["make"]).strip().upper()
        model = str(row["model"]).strip()
        year = int(row["year"])
        key = f"{make}||{model}||{year}"

        entry = _cache_get_entry(cache, key)
        if entry is not None and _cache_entry_usable(entry):
            cc = entry.get("cc")
            cc_src = entry.get("cc_src")
            fuel = entry.get("fuel")
            fuel_src = entry.get("fuel_src")
            results[key] = (cc, cc_src, fuel, fuel_src)
            if cc_src:
                cc_source_counts[cc_src] += 1
            if fuel_src:
                fuel_source_counts[fuel_src] += 1
            if (i % 500) == 0 or i == total_keys:
                print(f"  [{i}/{total_keys}] [CACHED] ...")
            continue

        cc, cc_src, fuel, fuel_src = lookup_cc_fuel(make, model, year, fe_df)
        cache["cc"][key] = {
            "cc": cc,
            "cc_src": cc_src,
            "fuel": fuel,
            "fuel_src": fuel_src,
            "v": CACHE_VERSION,
        }
        dirty_cache = True
        if (i % 50) == 0 or i == total_keys:
            save_cache(cache)
            dirty_cache = False

        results[key] = (cc, cc_src, fuel, fuel_src)
        if cc_src:
            cc_source_counts[cc_src] += 1
        if fuel_src:
            fuel_source_counts[fuel_src] += 1

        cc_status = f"{cc}cc via {cc_src}" if cc is not None else "cc=none"
        fuel_status = f"{fuel} via {fuel_src}" if fuel is not None else "fuel=none"
        print(f"  [{i}/{total_keys}] {make} {model} {year} -> {cc_status} | {fuel_status}")

    if dirty_cache:
        save_cache(cache)

    # --- Build output dataframe ---
    engine_capacity = []
    fuel_types = []
    for _, row in df.iterrows():
        make = str(row["make"]).strip().upper()
        model = str(row["model"]).strip()
        year = int(row["year"])
        key = f"{make}||{model}||{year}"
        if key in results:
            cc, _, fuel, _ = results[key]
        else:
            entry = _cache_get_entry(cache, key)
            if entry is not None and _cache_entry_usable(entry):
                cc = entry.get("cc")
                fuel = entry.get("fuel")
            else:
                cc, fuel = None, None
        engine_capacity.append(cc)
        fuel_types.append(fuel)

    out_df = df.copy()
    out_df["engine_capacity"] = engine_capacity
    out_df["fuel_type"] = fuel_types
    out_df = out_df[["make", "model", "year", "engine_capacity", "fuel_type"]]

    # Rows with any missing value are candidates for manual review
    unmatched_df = out_df[
        out_df["engine_capacity"].isna() | out_df["fuel_type"].isna()
    ][["make", "model", "year", "engine_capacity", "fuel_type"]]

    # --- Summary ---
    total = len(out_df)
    cc_matched = int(out_df["engine_capacity"].notna().sum())
    fuel_matched = int(out_df["fuel_type"].notna().sum())
    both_matched = int(
        (out_df["engine_capacity"].notna() & out_df["fuel_type"].notna()).sum()
    )

    print("\n--- Enrichment Summary ---")
    print(f"Total rows        : {total}")
    print(f"CC matched        : {cc_matched} ({cc_matched / total * 100:.1f}%)")
    print(f"Fuel matched      : {fuel_matched} ({fuel_matched / total * 100:.1f}%)")
    print(f"Both matched      : {both_matched} ({both_matched / total * 100:.1f}%)")
    print(f"Neither matched   : {total - cc_matched - fuel_matched + both_matched}")

    if cc_source_counts:
        print("\nCC matches by source:")
        for src, cnt in sorted(cc_source_counts.items(), key=lambda x: -x[1]):
            print(f"  {src}: {cnt}")

    if fuel_source_counts:
        print("\nFuel matches by source:")
        for src, cnt in sorted(fuel_source_counts.items(), key=lambda x: -x[1]):
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
