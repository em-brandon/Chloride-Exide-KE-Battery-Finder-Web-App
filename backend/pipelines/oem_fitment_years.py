"""
OEM-fitment year source.

Second automated year source, used where ja.wikipedia can't help. It reads
the `oem_fitment` table (Exide's own global fitment guide, already loaded
into this database) rather than any network service, so it costs nothing,
has no rate limit, and runs in seconds.

Why it exists: ja.wikipedia documents JDM passenger cars well and commercial
vehicles barely at all. Measured over the Japanese-make cleanup pass, it left
170 nameplates unresolved, of which 133 — including every single Hino
nameplate — do have year data sitting in `oem_fitment`. For battery fitment
specifically this is arguably the better authority anyway: it is the
manufacturer's own guide, not a crowd-sourced encyclopedia.

Matching, strongest tier first:

  1. Chassis code. `oem_fitment.model` embeds manufacturer chassis codes in
     parentheses — "HIACE / COMMUTER BUS (TRH2_, KDH2_, LH2_, GDH2_) 2.5
     D-4D (KDH202)". CRSP's `model_number` yields the same kind of code
     ("3BA-TRH200V-..." -> "TRH200V"), so the two can be matched directly.
     Trailing underscores are family wildcards: "TRH2_" covers TRH200V,
     TRH224W and so on.

  2. Model name. Falls back to the name before the first parenthesis
     ("HIACE / COMMUTER BUS"), matched against our nameplate.

Guards, because this source has its own bad data — `year_from` values as low
as 1900 and `year_to` as high as 2048 exist in the table:

  * years outside [EARLIEST_CREDIBLE_YEAR, current year] are discarded
  * a NULL `year_to` means "still in production" and is capped the same way
    enrich_years.py caps open-ended spans, not left unbounded
  * candidates spanning more than MAX_SPAN_YEARS are rejected as
    nameplate-level rather than generation-level data

Returns the same result shape as pipelines.ja_wikipedia_years.get_ja_years()
so callers can treat the two sources interchangeably.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import text

CURRENT_YEAR = datetime.now(timezone.utc).year

# Below this, a year is dataset junk rather than a real production date.
# oem_fitment contains year_from values down to 1900.
EARLIEST_CREDIBLE_YEAR = 1950

# A single generation/fitment entry spanning longer than this is
# nameplate-level data, not the per-generation precision we need.
MAX_SPAN_YEARS = 30

# How long an open-ended (NULL year_to) fitment is assumed to run, mirroring
# enrich_years.MAX_OPEN_ENDED_SPAN_YEARS rather than defaulting to "now",
# which is the bug that put 243 variants on an artificial 2026 end date.
MAX_OPEN_ENDED_SPAN_YEARS = 20

_PAREN_RE = re.compile(r"\(([^)]*)\)")
_CODE_RE = re.compile(r"^[A-Z]{1,4}[0-9A-Z_]{1,8}$")


def _model_head(oem_model: str) -> str:
    """'HIACE / COMMUTER BUS (TRH2_, ...) 2.5 D-4D' -> 'HIACE / COMMUTER BUS'."""
    return oem_model.split("(")[0].strip().upper()


def chassis_patterns(oem_model: str) -> list[str]:
    """Chassis-code patterns embedded in an oem_fitment model string."""
    out = []
    for group in _PAREN_RE.findall(oem_model.upper()):
        for part in group.split(","):
            part = part.strip()
            if _CODE_RE.match(part):
                out.append(part)
    return out


def chassis_matches(pattern: str, code: str) -> bool:
    """
    True when a CRSP chassis code belongs to an oem_fitment chassis pattern.

    A trailing '_' marks a family wildcard ("TRH2_" -> any TRH2xx), so the
    comparison is a prefix test on the pattern's fixed part. Exact patterns
    still match exactly, and a short shared prefix alone is not enough —
    requiring at least MIN_PREFIX characters stops "K" or "TR" from matching
    half the catalogue.
    """
    MIN_PREFIX = 3
    if not pattern or not code:
        return False
    stem = pattern.rstrip("_")
    if len(stem) < MIN_PREFIX:
        return False
    return code.upper().startswith(stem)


def _clean_span(year_from, year_to):
    """Apply the credibility guards; return (lo, hi) or None if unusable."""
    if year_from is None:
        return None
    lo = int(year_from)
    if lo < EARLIEST_CREDIBLE_YEAR or lo > CURRENT_YEAR:
        return None
    if year_to is None:
        hi = min(lo + MAX_OPEN_ENDED_SPAN_YEARS, CURRENT_YEAR)
    else:
        hi = min(int(year_to), CURRENT_YEAR)
    if hi < lo:
        return None
    if hi - lo + 1 > MAX_SPAN_YEARS:
        return None
    return lo, hi


def _result(**overrides):
    base = {
        "make": None, "model": None, "source": "oem_fitment",
        "matched_on": None, "candidates": [],
        "year_from": None, "year_to": None, "status": None,
    }
    base.update(overrides)
    return base


def get_oem_years(conn, make: str, base_model: str, chassis_hint: str | None = None,
                  log=print) -> dict:
    """
    Resolve a make/nameplate to a production year span from oem_fitment.

    status is "matched" | "ambiguous" | "no_data". "ambiguous" means rows
    matched but disagreed on the span beyond what one generation can be —
    reported, never averaged into a guess.
    """
    rows = conn.execute(text(
        "SELECT DISTINCT model, year_from, year_to FROM oem_fitment"
        " WHERE upper(make) = upper(:mk)"
    ), {"mk": make}).fetchall()
    if not rows:
        return _result(make=make, model=base_model, status="no_data")

    head_needle = base_model.upper().strip()

    # Tier 1 — chassis code.
    if chassis_hint:
        spans = set()
        for r in rows:
            if any(chassis_matches(p, chassis_hint) for p in chassis_patterns(r.model)):
                span = _clean_span(r.year_from, r.year_to)
                if span:
                    spans.add(span)
        if spans:
            lo, hi = min(s[0] for s in spans), max(s[1] for s in spans)
            if hi - lo + 1 <= MAX_SPAN_YEARS:
                log(f"    [oem] chassis '{chassis_hint}' matched {len(spans)} span(s) -> {lo}-{hi}")
                return _result(make=make, model=base_model, matched_on="chassis_code",
                               year_from=lo, year_to=hi, status="matched",
                               candidates=sorted(spans))
            log(f"    [oem] chassis '{chassis_hint}' spans too wide ({lo}-{hi}) — ambiguous")
            return _result(make=make, model=base_model, matched_on="chassis_code",
                           candidates=sorted(spans), status="ambiguous")

    # Tier 2 — model name.
    spans = set()
    for r in rows:
        head = _model_head(r.model)
        if head == head_needle or head.startswith(head_needle + " ") \
                or head_needle.startswith(head + " ") or head == head_needle.split()[0]:
            span = _clean_span(r.year_from, r.year_to)
            if span:
                spans.add(span)
    if not spans:
        return _result(make=make, model=base_model, status="no_data")

    lo, hi = min(s[0] for s in spans), max(s[1] for s in spans)
    if hi - lo + 1 > MAX_SPAN_YEARS:
        log(f"    [oem] name '{base_model}' spans too wide ({lo}-{hi}) — ambiguous")
        return _result(make=make, model=base_model, matched_on="model_name",
                       candidates=sorted(spans), status="ambiguous")
    log(f"    [oem] name '{base_model}' matched {len(spans)} span(s) -> {lo}-{hi}")
    return _result(make=make, model=base_model, matched_on="model_name",
                   year_from=lo, year_to=hi, status="matched", candidates=sorted(spans))
