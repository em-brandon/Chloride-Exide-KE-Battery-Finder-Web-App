"""
fix_vehicle_years_phantom_dates.py
------------------------------------
One-off cleanup for phantom year rows in vehicle_years caused by defects
in pipelines/enrich_years.py that were fixed on 2026-08-05 (Wikidata's
unbounded nameplate-inception dates chief among them — see CLAUDE.md's
"Year-data remediation" PLAN section). Fixing those defects does not
retroactively correct rows already sitting in the table:
commit_crsp_staging() (admin_router.py) only ever inserts rows for keys
that don't already exist in vehicle_years, so a bad row already there is
never touched by re-running enrichment and committing through the normal
staging flow.

For every (make, base-model nameplate) group in vehicle_years, this
script asks pipelines/ja_wikipedia_years.get_ja_years() for the real
generation-level production years. Only a status=="matched" result is
trusted — a specific trim-matched generation with real start/end years,
the highest-precision signal available in this codebase (see CLAUDE.md's
2026-08-05 live-validation notes). Existing rows for that nameplate whose
year falls outside the matched generation's range are then deleted.
Nameplates ja.wikipedia can't confidently resolve (ambiguous, no
generations found, title not resolved, or throttled) are left completely
untouched and listed in the report instead — never guessed, never
deleted without a confirmed replacement.

Delete-only: this script does not insert replacement rows, since it has
no way to synthesize the engine_capacity/fuel a new vehicle_years row
needs (those come from CRSP source data, not from year-enrichment
sources). Re-running pipelines/enrich_years.py and committing through the
existing staging review flow is the correct way to fill any gaps this
script's deletions create — that pipeline is purely additive, which is
exactly the right shape for that job.

Usage (run from backend/, same convention as pipelines/*.py)
--------------------------------------------------------------
    python scripts/fix_vehicle_years_phantom_dates.py                  # dry-run, full table
    python scripts/fix_vehicle_years_phantom_dates.py --make TOYOTA    # dry-run, one make
    python scripts/fix_vehicle_years_phantom_dates.py --limit 20       # dry-run, first N nameplates
    python scripts/fix_vehicle_years_phantom_dates.py --verbose        # + ja.wikipedia's own per-call logging
    python scripts/fix_vehicle_years_phantom_dates.py --execute        # apply changes
    python scripts/fix_vehicle_years_phantom_dates.py --crsp-file uploads/crsp_cd5f4716.xlsx
        # also try each variant's CRSP model_number (Japanese type-approval/
        # chassis code, e.g. "3BA-VJA300W-GNUZZ") as a trim hint before the
        # base_model-only attempt -- a stronger signal, since it's the
        # vehicle's own factory chassis code rather than free-text trim
        # wording that may or may not appear in ja.wikipedia's prose.
        # These existing DB rows predate the vehicle_years.model_number
        # column, so it's read from the raw upload file, not the DB.

Takes a real backup (db_backup.create_backup()) immediately before
applying changes, logged to admin_backup_log with triggered_by set to
this script's name. Writes a vehicle_years_versions row + matching
vehicle_years_changelog entries (change_type='removed') for every
deleted row, in the same shape commit_crsp_staging() already writes —
so the change is revertible through the existing admin UI pipeline
version-history revert action, no bespoke undo path needed.

A full run researches ~550 nameplates against ja.wikipedia, which is
rate-limited to 1 request/second (enforced inside ja_wikipedia_years.py
itself) — expect ~15-30 minutes depending on cache warmth. Re-running
after a dry-run is much faster since ja_wikipedia_years.py caches
resolved titles/generations to cache/ja_wikipedia_cache.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sqlalchemy import text

import db_backup
from db import engine
from pipelines.model_name_utils import extract_base_model, extract_search_model, extract_chassis_code
from pipelines.ja_wikipedia_years import get_ja_years, ThrottledError
from pipelines.enrich_years import _resolve_end_year, _derive_trim_hint

SCRIPT_NAME = "fix_vehicle_years_phantom_dates.py"

# extract_base_model() deliberately retains one trailing marker beyond the
# nameplate root — a numeric generation number ("LAND CRUISER 250") or,
# unfiltered by extract_search_model()'s Western-trim-word stop list, a
# short JDM grade letter ("PRIUS G", "SIENTA X"). Baking that marker into
# the ja.wikipedia title search does nothing useful (title resolution is
# fuzzy/tolerant either way) and throws away the one signal that could
# have disambiguated which generation the row belongs to, since
# get_ja_years()'s trim_hint is derived from whatever's left over *after*
# stripping the full base_model as a prefix. Splitting it out here and
# feeding it back in as the trim_hint is what let Land Cruiser 250/200/70/80
# resolve to their correct generations in testing instead of landing
# "ambiguous" despite ja.wikipedia's own generation data being fine.
_JDM_GRADE_SUFFIX_MAX_LEN = 3


def _split_search_title_and_hint(make, base_model):
    """
    Split a nameplate group's base_model into (search_title, dropped_hint).

    search_title is passed to ja.wikipedia for title resolution.
    dropped_hint is whatever trailing marker extract_search_model() didn't
    already know to strip — reused as the trim-matching signal instead.
    """
    search_title = extract_search_model(make, base_model)
    dropped = base_model[len(search_title):].strip()
    if not dropped:
        tokens = base_model.split()
        if (len(tokens) > 1 and tokens[-1].isalpha() and tokens[-1].isupper()
                and len(tokens[-1]) <= _JDM_GRADE_SUFFIX_MAX_LEN):
            search_title = " ".join(tokens[:-1])
            dropped = tokens[-1]
    return search_title, dropped


def _load_nameplates(conn, make_filter=None):
    """
    Group vehicle_years rows by (make, extract_base_model(make, model)).

    Returns {(make, base_model): {"variants": {model_str, ...},
                                   "years": {model_str: {year, ...}}}}
    """
    query = "SELECT make, model, year FROM vehicle_years"
    params = {}
    if make_filter:
        query += " WHERE make = :make"
        params["make"] = make_filter
    rows = conn.execute(text(query), params).fetchall()

    nameplates = defaultdict(lambda: {"variants": set(), "years": defaultdict(set)})
    for r in rows:
        base = extract_base_model(r.make, r.model)
        entry = nameplates[(r.make, base)]
        entry["variants"].add(r.model)
        entry["years"][r.model].add(r.year)
    return nameplates


def _load_model_numbers(crsp_file, make_filter=None):
    """
    Load a (make, model) -> model_number map from the raw CRSP Excel, the
    same way dataprep.py reads it (header=1, then column-name cleaning).

    Best-effort join key against vehicle_years.model -- the raw CRSP model
    string can differ slightly from what's stored (e.g. dataprep.py strips
    a redundant leading make prefix). A miss on a given variant just means
    it falls through to the existing base_model-only matching below, same
    as when --crsp-file isn't given at all -- no correctness risk, only a
    missed opportunity for that one variant.
    """
    import pandas as pd

    df = pd.read_excel(crsp_file, header=1)
    df.columns = df.columns.str.strip().str.lower().str.replace(r'[\s\n]+', '_', regex=True)
    if make_filter:
        df = df[df["make"].astype(str).str.upper() == make_filter.upper()]

    mapping: dict[tuple, str] = {}
    for _, row in df.iterrows():
        make = str(row.get("make", "")).strip().upper()
        model = str(row.get("model", "")).strip().upper()
        mn = row.get("model_number")
        if make and model and mn and str(mn).strip() and str(mn).strip().lower() != "nan":
            mapping[(make, model)] = str(mn).strip()
    return mapping


def _resolve_ranges(matched):
    """
    Expand a matched generation into its list of (year_from, year_to)
    ranges, one per production cluster, each independently capped by
    _resolve_end_year().

    Some generations (Land Cruiser's 70系 chief among them, verified live:
    "1984年 - 2004年、2014年 - 2015年、2023年 -") had production stopped and
    resumed more than once — ja_wikipedia_years.py already captures this as
    a "clusters" list on the generation dict, but its own top-level
    year_from/year_to on that same dict is just the flattened earliest
    start and latest (possibly open) end. Capping *that* flattened pair
    with _resolve_end_year() — which assumes one continuous span with an
    uncertain end — silently invents a single 1984-2004 run and would
    delete the real 2014-2015 and 2023+ rows this same generation covers.
    Using each cluster's own bounds instead avoids that.
    """
    clusters = matched.get("clusters") or [{
        "year_from": matched["year_from"], "year_to": matched["year_to"],
    }]
    return [
        (c["year_from"], _resolve_end_year(c["year_from"], c["year_to"]))
        for c in clusters
    ]


def _research_nameplate(make, base_model, variants, log, model_numbers=None):
    """
    Resolve a nameplate's real production years via ja.wikipedia.

    Returns (ranges, "matched") on a confirmed generation match — ranges
    is a list of (year_from, year_to) tuples, one per production cluster
    (almost always just one) — or (None, status) for anything else —
    ambiguous, no match, title not resolved, throttled, or an unexpected
    error. A throttled or errored lookup is reported distinctly from a
    genuine "no data" miss, per ja_wikipedia_years.py's own contract: it
    must never be silently recorded as a confirmed absence.

    The digit-generation-number exact-match trick (e.g. "250" -> "250系")
    that used to live here as a script-local retry now lives in the shared
    pipelines.ja_wikipedia_years.match_trim_to_generation() itself, so
    every trim_hint passed to get_ja_years() below benefits automatically
    — no need to duplicate it at each call site.
    """
    representative = max(variants, key=len)
    base_trim_hint = _derive_trim_hint(make, base_model, representative)

    def _call(search_title, trim_hint):
        try:
            return get_ja_years(make, search_title, trim_hint=trim_hint, log=log), None
        except ThrottledError as exc:
            return None, f"throttled: {exc}"
        except Exception as exc:  # noqa: BLE001 - keep a 550-nameplate run alive past one bad lookup
            return None, f"error: {exc}"

    # Tier 0, only when --crsp-file was given: try every variant's CRSP
    # model_number-derived chassis code as the trim hint against base_model,
    # before anything text-derived. Verified live this resolves nameplates
    # the CRSP model *text* alone never can — e.g. "LAND CRUISER ZX" carries
    # no generation number or usable grade marker in its model string at
    # all, but its model_number's chassis segment ("VJA300W"/"URJ202W")
    # matches a specific real generation directly, since it's the vehicle's
    # own factory chassis code rather than free text that may or may not
    # appear in ja.wikipedia's prose.
    #
    # Deliberately does NOT stop at the first variant that matches — a real
    # bug found live: extract_base_model() collapses "LAND CRUISER ZX" and
    # "LAND CRUISER PRADO TX" into the same "LAND CRUISER" base_model
    # (Prado's "PRADO" third token isn't numeric, so it's dropped, exactly
    # like a trim word would be), even though Prado is a genuinely separate
    # Toyota model line with its own unrelated production history. Stopping
    # at the first variant's match applied one mainline Land Cruiser's
    # confident 2021-2026 range to all 12 variants in that group, including
    # every Prado row, flagging ~840 rows for deletion that included real
    # Prado years. Every variant with a resolvable chassis code is checked
    # instead; if they don't all agree on the same generation, the group is
    # a false collapse of two distinct vehicles and gets left as residue —
    # correctness over the extra coverage this tier would otherwise add.
    if model_numbers:
        matched_generations = {}  # chassis_code identity -> matched generation dict
        for variant in sorted(variants):
            chassis_hint = extract_chassis_code(model_numbers.get((make.upper(), variant.upper())))
            if not chassis_hint:
                continue
            result, err = _call(base_model, chassis_hint)
            if err:
                return None, err
            if result["status"] == "matched":
                gen = result["matched_generation"]
                identity = gen.get("chassis_code") or (gen.get("year_from"), gen.get("year_to"))
                matched_generations.setdefault(identity, gen)

        if len(matched_generations) == 1:
            return _resolve_ranges(next(iter(matched_generations.values()))), "matched"
        if len(matched_generations) > 1:
            return None, "mixed_generations_in_group"

    # First try base_model exactly as extract_base_model() produced it —
    # this is already correct for nameplates where the retained marker is
    # part of the real name rather than a trim suffix (e.g. "MARK X" is a
    # complete Toyota nameplate, not "MARK" + trim "X"; splitting it would
    # search ja.wikipedia for the wrong title). Only retry with the marker
    # split out — as a trim-matching hint instead of baked into the title
    # search — when this first attempt specifically comes back ambiguous,
    # since that's the failure mode splitting is meant to fix (a real
    # generation number/grade letter swallowed into the search query,
    # unavailable for match_trim_to_generation() to disambiguate with).
    result, err = _call(base_model, base_trim_hint)
    if err:
        return None, err

    if result["status"] == "ambiguous":
        search_title, dropped = _split_search_title_and_hint(make, base_model)
        if dropped and search_title != base_model:
            trim_hint = dropped if len(dropped) >= 2 else base_trim_hint
            retry, err = _call(search_title, trim_hint)
            if err:
                return None, err
            result = retry

    if result["status"] != "matched":
        return None, result["status"]

    return _resolve_ranges(result["matched_generation"]), "matched"


def _plan_deletions(years_by_model, ranges):
    """Return [(model, year), ...] for every existing row outside every range in `ranges`."""
    out = []
    for model, years in years_by_model.items():
        for y in sorted(years):
            if not any(rf <= y <= rt for rf, rt in ranges):
                out.append((model, y))
    return out


def _format_ranges(ranges):
    return ", ".join(f"{rf}-{rt}" for rf, rt in ranges)


def main():
    parser = argparse.ArgumentParser(
        description="Delete vehicle_years rows outside their nameplate's ja.wikipedia-confirmed production years."
    )
    parser.add_argument("--execute", action="store_true",
                         help="Apply changes. Without this flag only a dry-run is shown.")
    parser.add_argument("--make", default=None, help="Restrict to a single make (for smoke-testing).")
    parser.add_argument("--limit", type=int, default=None,
                         help="Cap the number of nameplates researched (for a quick sanity pass).")
    parser.add_argument("--verbose", action="store_true",
                         help="Show ja_wikipedia_years.py's own per-call log lines.")
    parser.add_argument("--crsp-file", default=None,
                         help="Raw CRSP Excel to pull model_number chassis codes from "
                              "(e.g. uploads/crsp_cd5f4716.xlsx) — tried as a trim hint "
                              "before base_model-only matching. Optional.")
    args = parser.parse_args()

    log = print if args.verbose else (lambda *a, **k: None)

    with engine.connect() as conn:
        nameplates = _load_nameplates(conn, make_filter=args.make)

    model_numbers = None
    if args.crsp_file:
        model_numbers = _load_model_numbers(args.crsp_file, make_filter=args.make)

    keys = sorted(nameplates.keys())
    if args.limit:
        keys = keys[: args.limit]

    print("=" * 72)
    print("  FIX VEHICLE_YEARS PHANTOM DATES —", "EXECUTING" if args.execute else "DRY RUN")
    print("=" * 72)
    scope_bits = []
    if args.make:
        scope_bits.append(f"make={args.make}")
    if args.limit:
        scope_bits.append(f"limit={args.limit}")
    if args.crsp_file:
        scope_bits.append(f"crsp_file={args.crsp_file} ({len(model_numbers)} model_numbers loaded)")
    scope = f" ({', '.join(scope_bits)})" if scope_bits else ""
    print(f"\nNameplates to research: {len(keys)}{scope}\n")

    confirmed_with_deletions = {}   # (make, base) -> {"ranges": [(yf, yt), ...], "deletions": [(model, year), ...]}
    confirmed_clean = []
    residue = []                    # (make, base, status)

    for i, (make, base) in enumerate(keys, 1):
        data = nameplates[(make, base)]
        print(f"  [{i}/{len(keys)}] {make} {base} ...", end=" ", flush=True)
        resolved, status = _research_nameplate(make, base, data["variants"], log, model_numbers=model_numbers)
        if resolved is None:
            print(f"UNCONFIRMED ({status})")
            residue.append((make, base, status))
            continue
        ranges = resolved
        deletions = _plan_deletions(data["years"], ranges)
        if deletions:
            print(f"MATCHED {_format_ranges(ranges)} — {len(deletions)} row(s) outside range")
            confirmed_with_deletions[(make, base)] = {"ranges": ranges, "deletions": deletions}
        else:
            print(f"MATCHED {_format_ranges(ranges)} — already clean")
            confirmed_clean.append((make, base))

    total_deletion_rows = sum(len(v["deletions"]) for v in confirmed_with_deletions.values())

    print("\n" + "-" * 72)
    print(f"Confirmed, rows to delete : {len(confirmed_with_deletions):>5} nameplates, {total_deletion_rows} rows")
    print(f"Confirmed, already clean  : {len(confirmed_clean):>5} nameplates")
    print(f"Unconfirmed (residue)     : {len(residue):>5} nameplates — left untouched")
    print("-" * 72)

    if confirmed_with_deletions:
        print("\nBy make:")
        by_make = defaultdict(int)
        for (make, _base), v in confirmed_with_deletions.items():
            by_make[make] += len(v["deletions"])
        for make, n in sorted(by_make.items(), key=lambda x: -x[1]):
            print(f"  {make:<20} {n:>5} rows")

        print("\nSample deletions (up to 30):")
        shown = 0
        for (make, _base), v in confirmed_with_deletions.items():
            for model, year in v["deletions"]:
                if shown >= 30:
                    break
                print(f"  {make:<15} {model:<30} {year}  (outside {_format_ranges(v['ranges'])})")
                shown += 1
            if shown >= 30:
                break
        if total_deletion_rows > 30:
            print(f"  ... and {total_deletion_rows - 30} more rows not shown")

    if residue:
        print(f"\nResidue — needs manual review (CLAUDE.md task item 7), {len(residue)} nameplates:")
        for make, base, status in residue:
            print(f"  {make:<15} {base:<30} ({status})")

    if not args.execute:
        print(f"\n[DRY RUN] No changes made. Re-run with --execute to apply.\n")
        return

    if not confirmed_with_deletions:
        print("\nNothing to delete.\n")
        return

    print("\nTaking a backup before applying changes...")
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        try:
            result = db_backup.create_backup()
            conn.execute(text(
                "INSERT INTO admin_backup_log (filename, size_bytes, status, error_detail, triggered_by, created_at)"
                " VALUES (:f, :s, 'success', NULL, :t, :c)"
            ), {"f": result.filename, "s": result.size_bytes, "t": SCRIPT_NAME, "c": now})
            print(f"  Backup created: {result.filename} ({result.size_bytes:,} bytes)")
        except db_backup.BackupError as exc:
            conn.execute(text(
                "INSERT INTO admin_backup_log (filename, size_bytes, status, error_detail, triggered_by, created_at)"
                " VALUES ('', NULL, 'failed', :e, :t, :c)"
            ), {"e": str(exc), "t": SCRIPT_NAME, "c": now})
            print(f"\n  ERROR — backup failed, aborting cleanup:\n  {exc}\n")
            sys.exit(1)

    print("\nApplying deletions...")
    version_id = str(uuid.uuid4())
    deleted_count = 0
    with engine.begin() as conn:
        max_ver = conn.execute(
            text("SELECT COALESCE(MAX(version_number), 0) FROM vehicle_years_versions")
        ).scalar() or 0
        conn.execute(text(
            "INSERT INTO vehicle_years_versions"
            " (id, version_number, committed_at, run_id, committed_count, updated_count,"
            "  removed_count, conflict_count, committed_by, initiated_by, notes)"
            " VALUES (:id, :vn, :now, NULL, 0, 0, 0, 0, :by, :by, :notes)"
        ), {
            "id": version_id, "vn": max_ver + 1, "now": now,
            "by": SCRIPT_NAME,
            "notes": "Phantom-year cleanup — rows outside ja.wikipedia-confirmed generation range",
        })

        for (make, _base), v in confirmed_with_deletions.items():
            for model, year in v["deletions"]:
                existing = conn.execute(text(
                    "SELECT engine_capacity, fuel, source FROM vehicle_years"
                    " WHERE make = :make AND model = :model AND year = :year"
                ), {"make": make, "model": model, "year": year}).fetchone()
                if existing is None:
                    continue  # already gone (e.g. removed by an earlier run)
                conn.execute(text(
                    "DELETE FROM vehicle_years WHERE make = :make AND model = :model AND year = :year"
                ), {"make": make, "model": model, "year": year})
                conn.execute(text(
                    "INSERT INTO vehicle_years_changelog"
                    " (version_id, make, model, year, change_type, old_values, new_values)"
                    " VALUES (:vid, :make, :model, :year, 'removed', :old, NULL)"
                ), {
                    "vid": version_id, "make": make, "model": model, "year": year,
                    "old": json.dumps({
                        "engine_capacity": existing.engine_capacity,
                        "fuel": existing.fuel,
                        "source": existing.source,
                    }),
                })
                deleted_count += 1

        conn.execute(text(
            "UPDATE vehicle_years_versions SET removed_count = :n WHERE id = :id"
        ), {"n": deleted_count, "id": version_id})

    print(f"\n  DONE")
    print(f"    Deleted: {deleted_count:,} rows")
    print(f"    Version: {version_id} (revertible via the admin UI pipeline version history)\n")


if __name__ == "__main__":
    main()
