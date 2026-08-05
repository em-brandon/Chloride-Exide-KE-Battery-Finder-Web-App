"""
validate_ja_wikipedia_years.py
-------------------------------
Live validation harness for pipelines/ja_wikipedia_years.py, per CLAUDE.md's
year-data remediation plan: "validate on a hand-labelled sample before any
bulk run." Runs get_ja_years() against the same 12 nameplates already
verified in the original investigation and prints every generation found
(chassis code, year range, extraction shape) for human sanity-check —
e.g. confirming Land Cruiser's 1951 BJ/FJ-type generation is a real,
distinct, correctly-dated generation rather than being wrongly assigned to
every later query about the nameplate (the original bug).

This is a human-reviewed report, not a pass/fail assertion — there is no
existing ground-truth dataset to assert against yet. No trim_hint is passed
(this validates nameplate-level resolution + generation extraction; trim
disambiguation is exercised separately by the pipeline once wired in).

Usage
-----
    python scripts/validate_ja_wikipedia_years.py               # all 12 nameplates
    python scripts/validate_ja_wikipedia_years.py --no-cache     # force fresh fetches
    python scripts/validate_ja_wikipedia_years.py --make TOYOTA --model "LAND CRUISER"
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# This script prints ja.wikipedia article titles and generation labels
# (Japanese text) to stdout. Windows consoles commonly default to a cp1252
# code page, which raises UnicodeEncodeError on that output — reconfigure
# to UTF-8 defensively rather than requiring PYTHONIOENCODING to be set.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipelines.ja_wikipedia_years import ThrottledError, get_ja_years

# The 12 nameplates verified in the original 2026-08-03 investigation
# (CLAUDE.md's "Coverage sample" list), plus Land Cruiser as the headline
# case the whole source exists to fix.
SAMPLE_NAMEPLATES = [
    ("DAIHATSU", "HIJET"),
    ("TOYOTA", "LAND CRUISER"),
    ("TOYOTA", "CROWN"),
    ("MAZDA", "BONGO"),
    ("VOLKSWAGEN", "GOLF"),
    ("MITSUBISHI", "MINICAB"),
    ("SUBARU", "SAMBAR"),
    ("TOYOTA", "HIACE"),
    ("MITSUBISHI", "DELICA"),
    ("MERCEDES-BENZ", "E-CLASS"),
    ("NISSAN", "CARAVAN"),
    ("HINO", "DUTRO"),
]


def _print_result(make: str, model: str, result: dict, elapsed: float) -> None:
    score = result.get("match_score")
    score_flag = ""
    if isinstance(score, (int, float)) and score < 70:
        score_flag = f"  <-- LOW CONFIDENCE ({score:.1f}), verify manually"
    print(f"\n{make} {model}")
    print(f"  status: {result['status']}   elapsed: {elapsed:.2f}s")
    print(f"  ja_title: {result['ja_title']!r}   method: {result['resolution_method']!r}{score_flag}")
    print(f"  generations found: {len(result['generations'])}")
    for g in result["generations"]:
        label = g["chassis_code"] or "(unlabelled)"
        ordinal = f"{g['ordinal']} " if g["ordinal"] else ""
        print(f"    [{g['shape']:7s}] {ordinal}{label}: {g['year_from']}-{g['year_to'] or 'present'}")
    if result["matched_generation"]:
        mg = result["matched_generation"]
        print(f"  matched_generation: {mg['chassis_code']!r} ({mg['year_from']}-{mg['year_to']})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-cache", action="store_true", help="bypass local cache, force fresh API calls")
    parser.add_argument("--make", help="run a single make instead of the full sample (requires --model)")
    parser.add_argument("--model", help="run a single model instead of the full sample (requires --make)")
    args = parser.parse_args()

    if args.make or args.model:
        if not (args.make and args.model):
            parser.error("--make and --model must be given together")
        nameplates = [(args.make.upper(), args.model.upper())]
    else:
        nameplates = SAMPLE_NAMEPLATES

    use_cache = not args.no_cache
    throttled = 0
    status_counts: dict = {}
    total_start = time.time()

    for make, model in nameplates:
        t0 = time.time()
        try:
            result = get_ja_years(make, model, trim_hint=None, log=print, use_cache=use_cache)
        except ThrottledError as exc:
            # get_ja_years() itself catches ThrottledError internally and
            # returns status="throttled" — this except is a defensive
            # backstop only, and must NOT be treated as a normal miss either.
            throttled += 1
            print(f"\n{make} {model}\n  THROTTLED (uncaught): {exc}")
            continue
        elapsed = time.time() - t0
        status_counts[result["status"]] = status_counts.get(result["status"], 0) + 1
        if result["status"] == "throttled":
            throttled += 1
        _print_result(make, model, result, elapsed)

    total_elapsed = time.time() - total_start
    print("\n" + "=" * 60)
    print(f"Ran {len(nameplates)} nameplates in {total_elapsed:.1f}s")
    print(f"Status breakdown: {status_counts}")
    if throttled:
        print(f"THROTTLED: {throttled} — these were NOT recorded as misses; re-run to retry.")
    print("Review each nameplate's generation list above for plausibility")
    print("(distinct, non-overlapping year ranges; no 1900s-era outliers unless genuinely historical).")


if __name__ == "__main__":
    main()
