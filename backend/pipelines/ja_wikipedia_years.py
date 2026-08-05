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
