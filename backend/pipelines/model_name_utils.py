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
    if not tokens:
        return model_name
    base_tokens = tokens[:2]
    # Retain a 3rd token when it's purely numeric — a generation/series
    # marker (e.g. "LAND CRUISER 250 VX" -> "LAND CRUISER 250"), not an
    # engine/trim code (e.g. "3 SERIES 320D ..." correctly stays "3 SERIES"
    # since "320D" contains a letter and isn't purely numeric, so it's left
    # for extract_search_model()'s own digit-token stop rule to drop).
    # The old unconditional 2-token cap discarded generation numbers
    # entirely, collapsing e.g. "LAND CRUISER 250" and "LAND CRUISER 300"
    # into the same base model — losing generation granularity for the
    # cache key and any caller (CarAPI's inline match, ja.wikipedia's trim
    # hint) that uses this output directly rather than through
    # extract_search_model().
    if len(tokens) > 2 and tokens[2].isdigit():
        base_tokens.append(tokens[2])
    return " ".join(base_tokens)


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
