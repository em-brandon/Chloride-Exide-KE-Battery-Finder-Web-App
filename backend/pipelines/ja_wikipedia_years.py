"""
Japanese Wikipedia year-enrichment source.

Why this exists: the English-Wikipedia source in enrich_years.py calls
`prop=extracts`, which only returns a page's nameplate-level lead paragraph —
not per-generation production data. Combined with Wikidata's unbounded P571
inception date, this produced wrong values (e.g. a Land Cruiser listed from
1951, its nameplate's founding year, not any real generation's start).

ja.wikipedia.org publishes accurate, structured, generation-level production
year ranges with chassis codes for both Japanese and Western makes — verified
live against real articles during this module's design (see CLAUDE.md's
year-data remediation writeup). Two extraction shapes are used, and either can
be present without the other:
  1. Section headings, e.g. "40系（1960年 - 1984年）" or "初代 DW系（1996年 - 2002年）"
  2. Infobox `販売期間` (sales period) template parameters

This module fetches `action=parse&prop=wikitext` (not `prop=extracts`) and
parses the raw wikitext with mwparserfromhell, which correctly isolates a
template parameter's value even when it contains nested templates (e.g. a
`{{Ublist|...}}` or `{{dl2|...}}` wrapping multiple labeled sub-ranges) — a
naive regex over raw wikitext would get confused by the nested `{{`/`}}`/`|`
characters and either mis-extract or silently return nothing.

Rate limiting is mandatory and its contract is deliberately strict: a
throttled response (non-200, non-JSON, or wrong Content-Type — the signature
Wikipedia returns when it starts rate-limiting) raises ThrottledError rather
than being treated as "no data". A prior 0.35s request spacing caused exactly
this failure mode in production — throttled HTML responses silently recorded
as misses. This module never does that; every fetch function propagates
ThrottledError to its caller instead of swallowing it.
"""

import re
import time

import mwparserfromhell
import requests
import urllib3
from rapidfuzz import fuzz, utils as fuzz_utils

from pipelines.model_name_utils import to_search_make, extract_search_model

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Minimum rapidfuzz score between the query and a resolved title's (or its
# round-tripped English equivalent's) text before it's trusted. Without this,
# blindly taking the #1 search hit produces wrong vehicles silently — verified
# live: "Mazda DEMIO" resolved to Autozam, "Volkswagen GOLF" to the Atlas,
# "Hino DUTRO" to the Ranger, all via an unrelated top search result.
#
# token_sort_ratio (not token_set_ratio) is deliberately used, with
# processor=default_process for case-insensitivity. token_set_ratio is
# subset-tolerant, which was verified to make a bare make-name company page
# ("Daihatsu", "Nissan", "Toyota") score 100 against "Daihatsu HIJET" —
# beating the actual model article ("Daihatsu Hijet") on ties. token_sort_ratio
# penalizes the length/token-count mismatch a bare company name has against a
# "Make Model" query, correctly ranking the real model article above it.
_MIN_TITLE_MATCH_SCORE = 55

# en.wikipedia's search sometimes top-matches a "List of X vehicles"
# disambiguation/index page rather than the model's own article (e.g. "Mazda
# DEMIO automobile" -> "List of Mazda vehicles"). Its ja langlink is a list
# page with no generation data, so it must be rejected rather than followed.
_LIST_PAGE_RE = re.compile(r'^list of\b', re.IGNORECASE)
_JA_LIST_PAGE_RE = re.compile(r'一覧$')

EN_WIKI_API = "https://en.wikipedia.org/w/api.php"
JA_WIKI_API = "https://ja.wikipedia.org/w/api.php"

# Verified-safe spacing between requests (to either host). 0.35s caused 12
# consecutive throttled responses during this module's investigation; 1.0s
# ran cleanly for ~30 minutes straight. Do not lower this without re-verifying.
MIN_REQUEST_INTERVAL = 1.0

SESSION = requests.Session()
SESSION.verify = False
SESSION.headers["User-Agent"] = (
    "BatteryFinderBot/1.0 (battery-finder research; contact: battery-finder-bot@example.com)"
)


def _title_score(a: str, b: str) -> float:
    return fuzz.token_sort_ratio(a, b, processor=fuzz_utils.default_process)


class ThrottledError(Exception):
    """
    Raised when a Wikipedia response looks throttled/rate-limited rather than
    a genuine "no data" result.

    Callers MUST NOT treat this the same as a normal miss — see module
    docstring. Catch it explicitly wherever a miss would otherwise be cached
    or recorded, and skip recording anything for this run instead.
    """


_last_request_at = 0.0


def _rate_limit_wait():
    """Block until at least MIN_REQUEST_INTERVAL has passed since the last request."""
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    remaining = MIN_REQUEST_INTERVAL - elapsed
    if remaining > 0:
        time.sleep(remaining)
    _last_request_at = time.monotonic()


def _is_throttled_response(resp) -> bool:
    """
    True if `resp` looks like a throttled/rate-limited response rather than a
    genuine JSON API result. Pure function (no I/O, no sleeping) so it's
    directly unit-testable without mocking the transport layer — just build a
    fake response-like object with `.status_code`, `.headers`, and `.json()`.
    """
    if resp.status_code != 200:
        return True
    content_type = resp.headers.get("Content-Type", "")
    if "json" not in content_type.lower():
        return True
    try:
        resp.json()
    except ValueError:
        return True
    return False


def _api_get(url: str, params: dict, log=print, attempts: int = 3) -> dict:
    """
    GET `url` with rate limiting and retry-with-backoff (same 3-attempt,
    escalating-wait pattern already used by enrich_years.py's other sources).

    Returns the parsed JSON dict on success — including a "normal miss" like
    an empty search-results list, which is valid JSON and not a throttle.
    Raises ThrottledError if every attempt looks throttled or errors — never
    returns None/{} to signal a throttle, since that would be indistinguishable
    from a genuine empty result to the caller.
    """
    last_exc = None
    for attempt in range(attempts):
        _rate_limit_wait()
        try:
            resp = SESSION.get(url, params=params, timeout=15)
        except requests.RequestException as exc:
            last_exc = exc
            wait = 5 * (attempt + 1)
            log(f"    [ja-wiki] request error ({exc}), waiting {wait}s...")
            time.sleep(wait)
            continue
        if _is_throttled_response(resp):
            wait = 5 * (attempt + 1)
            log(
                f"    [ja-wiki] THROTTLED (status={resp.status_code}, "
                f"content-type={resp.headers.get('Content-Type')}), waiting {wait}s..."
            )
            time.sleep(wait)
            continue
        return resp.json()
    raise ThrottledError(f"Exhausted {attempts} attempts against {url} — last error: {last_exc}")


def _fetch_ja_langlink(en_title: str, log=print) -> str | None:
    ll_data = _api_get(
        EN_WIKI_API,
        {"action": "query", "prop": "langlinks", "lllang": "ja",
         "titles": en_title, "format": "json", "utf8": 1},
        log=log,
    )
    pages = ll_data.get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    langlinks = page.get("langlinks", [])
    return langlinks[0]["*"] if langlinks else None


def _fetch_en_langlink(ja_title: str, log=print) -> str | None:
    ll_data = _api_get(
        JA_WIKI_API,
        {"action": "query", "prop": "langlinks", "lllang": "en",
         "titles": ja_title, "format": "json", "utf8": 1},
        log=log,
    )
    pages = ll_data.get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    langlinks = page.get("langlinks", [])
    return langlinks[0]["*"] if langlinks else None


def resolve_ja_title(make: str, model_name: str, log=print) -> dict:
    """
    Resolve a make/model pair to a ja.wikipedia.org article title.

    Primary path: search en.wikipedia (top 3 candidates), then follow the
    best-scoring candidate's langlink to ja — e.g. Renault's JDM badge
    "Lutecia" -> en "Renault Clio" -> ja "ルノー・クリオ", no translation
    layer needed.

    Fallback (no acceptable langlink found): search ja.wikipedia directly
    (top 3 candidates), then round-trip each back to English via its own
    langlink and score that against the query — flagged with a
    lower-confidence resolution method since it adds a hop.

    Neither path trusts a raw #1 search hit: verified live that doing so
    silently resolves to the wrong vehicle (Mazda DEMIO -> Autozam,
    Volkswagen GOLF -> Atlas, Hino DUTRO -> Ranger) whenever the top hit is
    an index/list page or an unrelated model that happens to rank first.
    Every candidate is scored with rapidfuzz against the query and rejected
    below _MIN_TITLE_MATCH_SCORE rather than guessed.

    Returns {"title": str|None, "method": "langlink"|"ja_direct_search"|None,
             "match_score": int|None}.
    Raises ThrottledError on a throttled request (propagated, not swallowed).
    """
    search_make = to_search_make(make)
    search_model = extract_search_model(make, model_name)
    query = f"{search_make} {search_model} automobile"
    target = f"{search_make} {search_model}"

    data = _api_get(
        EN_WIKI_API,
        {"action": "query", "list": "search", "srsearch": query,
         "srlimit": 3, "format": "json", "utf8": 1},
        log=log,
    )
    results = data.get("query", {}).get("search", [])
    en_candidates = [r["title"] for r in results if not _LIST_PAGE_RE.match(r["title"])]
    scored_en = sorted(
        ((t, _title_score(t, target)) for t in en_candidates),
        key=lambda x: -x[1],
    )
    if scored_en:
        log(f"    [ja-wiki] en candidates for '{target}': {scored_en}")

    for en_title, score in scored_en:
        if score < _MIN_TITLE_MATCH_SCORE:
            log(f"    [ja-wiki] en '{en_title}' score {score} < {_MIN_TITLE_MATCH_SCORE} — stopping (rest are worse)")
            break
        ja_title = _fetch_ja_langlink(en_title, log=log)
        if not ja_title:
            log(f"    [ja-wiki] en '{en_title}' has no ja langlink")
            continue
        if _JA_LIST_PAGE_RE.search(ja_title):
            log(f"    [ja-wiki] ja '{ja_title}' looks like an index/list page — rejecting")
            continue
        log(f"    [ja-wiki] '{query}' -> en '{en_title}' (score {score}) -> ja '{ja_title}' [langlink]")
        return {"title": ja_title, "method": "langlink", "match_score": score}

    # Fallback: search ja.wikipedia directly, then round-trip each candidate
    # back to English to score it — a raw ja title can't be fuzzy-scored
    # against a Latin-script query directly (different scripts entirely).
    ja_data = _api_get(
        JA_WIKI_API,
        {"action": "query", "list": "search", "srsearch": query,
         "srlimit": 3, "format": "json", "utf8": 1},
        log=log,
    )
    ja_results = ja_data.get("query", {}).get("search", [])
    best_title, best_score = None, -1
    for r in ja_results:
        ja_candidate = r["title"]
        if _JA_LIST_PAGE_RE.search(ja_candidate):
            continue
        rt_en_title = _fetch_en_langlink(ja_candidate, log=log) or ja_candidate
        score = _title_score(rt_en_title, target)
        log(f"    [ja-wiki] ja candidate '{ja_candidate}' round-trips to '{rt_en_title}' (score {score})")
        if score > best_score:
            best_title, best_score = ja_candidate, score

    if best_title is not None and best_score >= _MIN_TITLE_MATCH_SCORE:
        log(f"    [ja-wiki] '{query}' -> ja '{best_title}' (score {best_score}) [direct search]")
        return {"title": best_title, "method": "ja_direct_search", "match_score": best_score}

    log(f"    [ja-wiki] no ja.wikipedia title resolved for '{query}' (best score {best_score})")
    return {"title": None, "method": None, "match_score": None}


def fetch_ja_wikitext(title: str, log=print) -> str:
    """
    Fetch the raw wikitext of a ja.wikipedia article via
    `action=parse&prop=wikitext` — NOT `prop=extracts`, which only returns
    the nameplate-level lead paragraph (see module docstring for why that
    distinction matters).
    """
    data = _api_get(
        JA_WIKI_API,
        {"action": "parse", "page": title, "prop": "wikitext", "format": "json"},
        log=log,
    )
    if "error" in data:
        log(f"    [ja-wiki] parse error for '{title}': {data['error']}")
        return ""
    return data.get("parse", {}).get("wikitext", {}).get("*", "")


# =========================
# GENERATION-HEADING PARSING
# =========================
#
# Verified against real articles (Toyota Land Cruiser, Toyota Crown, Mazda
# Demio) rather than assumed from a single idealized example. Two heading
# shapes are both real and common:
#   "初代 DW系（1996年 - 2002年）"      — ordinal + chassis code (Demio, Crown)
#   "40系（1960年 - 1984年）"          — chassis code only, NO ordinal (Land
#                                        Cruiser — its most-cited article!)
# A naive parser requiring the ordinal marker would miss the majority of
# real headings on pages like Land Cruiser. Also observed and handled:
#   - multiple date ranges in one heading, comma-separated, when a chassis
#     code went out of and back into production:
#     "70系（1984年 - 2004年、2014年 - 2015年、2023年 -）"
#   - open-ended ranges: "300系（2021年 - ）" (still in production)
#   - multiple chassis codes joined by "/": "初代 RS型/S2#型/S3#型（1955年 - 1962年）"

_JP_ERA_OFFSETS = {
    "令和": 2018,  # Reiwa: 令和1年 = 2019
    "平成": 1988,  # Heisei: 平成1年 = 1989
    "昭和": 1925,  # Showa: 昭和1年 = 1926
    "大正": 1911,  # Taisho: 大正1年 = 1912
    "明治": 1867,  # Meiji: 明治1年 = 1868
}
_ERA_NAMES_RE = "|".join(_JP_ERA_OFFSETS)

# One "YYYY年" or "元号N年" token, with optional month/day — used via
# finditer() against an already-isolated date-range segment, never combined
# with itself into one bigger pattern (stdlib re disallows duplicate named
# groups in a single pattern).
_YEAR_TOKEN_RE = re.compile(
    rf'(?:(?P<era>{_ERA_NAMES_RE})(?P<era_year>\d{{1,2}})|(?P<year>\d{{3,4}}))年'
    rf'(?:(?P<month>\d{{1,2}})月)?(?:(?P<day>\d{{1,2}})日)?'
)

# A generation heading's leading ordinal, if present — often absent (see above).
_ORDINAL_RE = re.compile(r'^(初代|\d+代目)\s*')

_PAREN_OPEN = "（("
_PAREN_CLOSE = "）)"


def _year_token_to_int(m: "re.Match") -> int | None:
    if m.group("era"):
        return _JP_ERA_OFFSETS[m.group("era")] + int(m.group("era_year"))
    if m.group("year"):
        return int(m.group("year"))
    return None


def _parse_date_clusters(text: str) -> list:
    """
    Split `text` (the content of a heading's parenthesis) on ideographic/ASCII
    commas into one or more date-range clusters, each describing one
    production span. A cluster with only one year token is open-ended (still
    in production, or at least no end date is stated) — never defaulted to
    the current year here; that clamp belongs to the caller, matching every
    other source in enrich_years.py.
    """
    clusters = []
    for segment in re.split(r"[、,]", text):
        tokens = list(_YEAR_TOKEN_RE.finditer(segment))
        if not tokens:
            continue
        year_from = _year_token_to_int(tokens[0])
        if year_from is None:
            continue
        year_to = None
        if len(tokens) >= 2:
            year_to = _year_token_to_int(tokens[1])
        clusters.append({
            "year_from": year_from,
            "year_to": year_to,
            "open_ended": year_to is None,
            "raw": segment.strip(),
        })
    return clusters


def _combine_clusters(clusters: list) -> tuple:
    """
    Collapse one or more date-range clusters into a single (year_from,
    year_to) envelope for the generation as a whole: earliest start across
    all clusters, latest end across all clusters — unless the chronologically
    last cluster is open-ended, in which case year_to is None (still in
    production as of the article).
    """
    if not clusters:
        return None, None
    year_from = min(c["year_from"] for c in clusters)
    if clusters[-1]["open_ended"]:
        year_to = None
    else:
        defined_ends = [c["year_to"] for c in clusters if c["year_to"] is not None]
        year_to = max(defined_ends) if defined_ends else None
    return year_from, year_to


def parse_generation_heading(title: str) -> dict | None:
    """
    Parse one level-2 heading title. Returns None if it doesn't describe a
    production period (e.g. "概要", "系譜", "モータースポーツ", "脚注" — every
    non-generation section on a car article) — driven entirely by "does this
    heading contain a parenthesized cluster with at least one year", not by
    requiring an ordinal marker, since that marker is often absent on real
    pages (see module-level comment above).
    """
    open_idx = next((i for i, ch in enumerate(title) if ch in _PAREN_OPEN), None)
    if open_idx is None:
        return None
    close_idx = next(
        (i for i in range(len(title) - 1, open_idx, -1) if title[i] in _PAREN_CLOSE),
        None,
    )
    if close_idx is None:
        return None

    clusters = _parse_date_clusters(title[open_idx + 1:close_idx])
    if not clusters:
        return None

    year_from, year_to = _combine_clusters(clusters)
    label_part = title[:open_idx].strip()
    ordinal_m = _ORDINAL_RE.match(label_part)
    ordinal = ordinal_m.group(1) if ordinal_m else None
    chassis_code = label_part[ordinal_m.end():].strip() if ordinal_m else label_part

    return {
        "raw_title": title,
        "ordinal": ordinal,
        "chassis_code": chassis_code,
        "year_from": year_from,
        "year_to": year_to,
        "clusters": clusters,
        "shape": "heading",
    }


def extract_generations_from_headings(wikitext: str, log=print) -> list:
    """
    Walk every level-2 (`==...==`) section of `wikitext` and return one dict
    per heading that parses as a generation, each carrying its section body
    text (everything until the next level-2-or-higher heading) for later
    trim matching. Level-3+ subsections (e.g. "=== 年表 ===", "=== 歴史===")
    are deliberately not treated as separate generations — they're narrative
    detail within a generation's own section, not additional generations.
    """
    code = mwparserfromhell.parse(wikitext)
    generations = []
    for section in code.get_sections(levels=[2], include_headings=True):
        headings = section.filter_headings()
        if not headings:
            continue
        title = str(headings[0].title).strip()
        parsed = parse_generation_heading(title)
        if parsed is None:
            continue
        parsed["section_body"] = str(section)
        generations.append(parsed)
        log(f"    [ja-wiki] generation heading: '{title}' -> {parsed['year_from']}-{parsed['year_to']}")
    return generations
