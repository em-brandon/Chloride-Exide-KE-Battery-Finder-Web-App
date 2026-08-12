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


def extract_chassis_code(model_number) -> str | None:
    """
    Pull the real chassis/type code out of a CRSP "model number" value.

    CRSP's model_number column holds Japanese vehicle type-approval codes in
    the form "<classification prefix>-<chassis code>[-<market/trim suffix>]",
    e.g. "3BA-VJA300W-GNUZZ" (classification "3BA", chassis code "VJA300W")
    or the 2-segment "DBA-FK7" (chassis code "FK7") -- verified live against
    real CRSP data (backend/uploads/crsp_cd5f4716.xlsx) that this segment is
    what actually appears in ja.wikipedia generation prose/chassis codes
    (e.g. "VJA300W" substring-matches Land Cruiser's "300系" generation),
    unlike the full model_number string or the classification prefix alone.

    Real Japanese classification prefixes are short (1-2 digits + 1-3
    letters, e.g. "3BA", "DBA", "6AA" -- always <=3 characters). Some CRSP
    rows have no prefix segment at all, just "<chassis code>-<suffix>"
    (e.g. "FJA300-407", chassis code "FJA300") -- verified live that
    blindly treating every 2-segment value as prefix-code misreads this
    shape and extracts "407" (garbage) instead of "FJA300" (which contains
    the real "300" generation number). A first segment longer than 3
    characters means there's no real prefix, so the first segment itself
    is the code.

    A bare code with no dash ("F5CWGC") is returned unchanged. Non-JDM
    model_number values (VIN fragments, occasional garbage like a leaked
    trim description) just won't match anything downstream -- no special
    detection needed, same as any other unresolvable trim hint.
    """
    if not model_number:
        return None
    mn = str(model_number).strip()
    # pandas represents a missing value as float NaN, which is truthy
    # (unlike 0.0) so it survives the `not model_number` check above and
    # stringifies to the literal text "nan" -- caught explicitly here
    # rather than upstream, since every caller reads model_number out of a
    # DataFrame row where this can occur.
    if not mn or mn.lower() == "nan":
        return None
    parts = mn.split('-')
    if len(parts) == 1:
        return parts[0]
    return parts[1] if len(parts[0]) <= 3 else parts[0]
