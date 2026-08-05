"""
Shared make/model name-cleaning helpers.

Extracted out of enrich_years.py so both enrich_years.py and ja_wikipedia_years.py
can use the same search-query normalisation without importing from each other.
"""

import re

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


def to_search_make(make: str) -> str:
    """Normalise make name for external search queries (Wikipedia / Wikidata)."""
    mapped = MAKE_MAP.get(make.strip().upper())
    if mapped:
        return mapped.title()
    return make.strip().title()


def extract_base_model(make, model_name):
    name = model_name.strip()
    for prefix in [make.strip(), make.split()[0].strip()]:
        if name.upper().startswith(prefix.upper()):
            name = name[len(prefix):].strip()
            break
    tokens = name.split()
    return " ".join(tokens[:2]) if tokens else model_name


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
