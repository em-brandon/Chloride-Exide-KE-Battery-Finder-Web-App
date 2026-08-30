"""
rebuild_web_validation.py
-------------------------
Clear and regenerate web_battery_validation for a group of makes.

WHY CLEARING IS REQUIRED, NOT OPTIONAL
--------------------------------------
web_battery_validate.main() skips any (make_n, model_n, year) already present
in web_battery_validation — that incremental behaviour is what makes normal
re-runs cheap. It also means a rebuild that doesn't clear first does nothing
at all for rows that already exist. Since the point here is to replace rows
built on phantom years and on the pre-fix technology value, the target makes'
rows must be deleted before the run.

Only the selected makes are cleared, so a JDM rebuild leaves Western rows
intact until their own turn.

The pipeline's own file caches are NOT cleared: the search query is built
only from make/model/year, so a cached result for a combo that still exists
is the same answer a re-fetch would produce. cache/battery_validate_cache.json
should have had scripts/fix_validate_cache_technology.py run over it first,
which corrects the one field the cache had wrong.

Usage (run from backend/)
-------------------------
    python scripts/rebuild_web_validation.py --group jdm
    python scripts/rebuild_web_validation.py --group jdm --execute
    python scripts/rebuild_web_validation.py --group western --execute
    python scripts/rebuild_web_validation.py --makes TOYOTA,NISSAN --execute
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Windows consoles default to cp1252, and piping to tee/a file makes Python use
# that locale encoding rather than UTF-8. The pipeline logs en-dashes (year
# buckets), arrows (Phase 2 result lines) and Japanese chassis codes, so any of
# those raises UnicodeEncodeError *inside the per-row worker* — which the row's
# own `except Exception` catches and reports as "[FATAL-SKIP] row crashed
# unexpectedly", losing every row while looking like a data problem rather than
# an encoding one. errors="replace" additionally guarantees a stray character
# can never abort a run that is otherwise working.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text

import db_backup
from db import engine

SCRIPT_NAME = "rebuild_web_validation.py"

JDM_MAKES = [
    "TOYOTA", "NISSAN", "DAIHATSU", "MITSUBISHI", "HONDA", "MAZDA", "SUBARU",
    "HINO", "ISUZU", "SUZUKI", "LEXUS", "NISSAN DIESEL/UD", "MITSUBISHI FUSO",
]


def western_makes(conn):
    rows = conn.execute(text(
        "SELECT DISTINCT make FROM vehicle_years ORDER BY make")).fetchall()
    return [r.make for r in rows if r.make.upper() not in {m.upper() for m in JDM_MAKES}]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--group", choices=["jdm", "western", "all"], default=None)
    p.add_argument("--makes", default=None, help="Comma-separated make list.")
    p.add_argument("--execute", action="store_true",
                   help="Actually clear and rebuild. Default shows the plan only.")
    p.add_argument("--phase", choices=["phase1", "phase2", "both"], default="both")
    p.add_argument("--min-year", type=int, default=None,
                   help="Skip combos older than this year. Pre-2000 buckets are ~16%% of "
                        "rows but only ~5%% of variants, and are concentrated in the "
                        "residue years no source could verify — the weakest use of a "
                        "metered search budget.")
    p.add_argument("--one-make-at-a-time", action="store_true",
                   help="BROKEN — DO NOT USE. See the guard below: each make's run "
                        "TRUNCATEs web_battery_staging, destroying every previously "
                        "completed make. Kept only so the flag fails loudly instead of "
                        "silently discarding a multi-hour run.")
    args = p.parse_args()

    # web_battery_validate.main() calls _upsert_rows(truncate_staging_first=True),
    # which TRUNCATEs web_battery_staging at the start of every invocation. Running
    # one make per invocation therefore wipes each finished make as the next starts,
    # leaving only the last one staged — a full 13-make run completed in 67 min and
    # left 883 Daihatsu rows, having silently destroyed the other twelve makes.
    # Staging is per-run by design, so all makes must be staged in a single call.
    if args.one_make_at_a_time:
        print("\n  ERROR — --one-make-at-a-time destroys results.\n"
              "  Each make TRUNCATEs web_battery_staging, so only the last make\n"
              "  survives. Re-run without this flag to stage every make together.\n")
        sys.exit(2)

    with engine.connect() as conn:
        if args.makes:
            makes = [m.strip().upper() for m in args.makes.split(",") if m.strip()]
        elif args.group == "western":
            makes = western_makes(conn)
        elif args.group == "all":
            makes = [r.make for r in conn.execute(text(
                "SELECT DISTINCT make FROM vehicle_years ORDER BY make")).fetchall()]
        else:
            makes = JDM_MAKES

        upper = [m.upper() for m in makes]
        existing = conn.execute(text(
            "SELECT count(*) FROM web_battery_validation WHERE upper(make_n) = ANY(:mk)"
        ), {"mk": upper}).scalar()
        combos = conn.execute(text(
            "SELECT count(DISTINCT (upper(trim(make)), model, year)) FROM vehicle_years"
            " WHERE upper(trim(make)) = ANY(:mk) AND year IS NOT NULL"
            "   AND (:my IS NULL OR year >= :my)"
        ), {"mk": upper, "my": args.min_year}).scalar()

    print("=" * 74)
    print("  REBUILD WEB VALIDATION —", "EXECUTING" if args.execute else "PLAN ONLY")
    print("=" * 74)
    print(f"\nMakes                 : {len(makes)}")
    print(f"  {', '.join(makes)}")
    print(f"\nRows to clear         : {existing:,}")
    print(f"Combos to rebuild     : {combos:,}")
    print(f"Phase                 : {args.phase}")
    print(f"Min year              : {args.min_year or '(none)'}")
    print(f"Sequential per make   : {args.one_make_at_a_time}")

    if not args.execute:
        print("\n[PLAN ONLY] Nothing changed. Re-run with --execute.\n")
        return

    print("\nTaking a backup before clearing...")
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        try:
            result = db_backup.create_backup()
            conn.execute(text(
                "INSERT INTO admin_backup_log (filename, size_bytes, status, error_detail,"
                " triggered_by, created_at) VALUES (:f, :s, 'success', NULL, :t, :c)"
            ), {"f": result.filename, "s": result.size_bytes, "t": SCRIPT_NAME, "c": now})
            print(f"  Backup created: {result.filename} ({result.size_bytes:,} bytes)")
        except db_backup.BackupError as exc:
            print(f"\n  ERROR — backup failed, aborting:\n  {exc}\n")
            sys.exit(1)

    from pipelines import web_battery_validate

    # log_callback only — the pipeline also prints internally, so passing a
    # printing callback as well duplicated every line in the first run's log.
    def _quiet(_line):
        pass

    groups = [[m] for m in makes] if args.one_make_at_a_time else [makes]
    started_all = time.monotonic()
    for i, group in enumerate(groups, 1):
        g_upper = [m.upper() for m in group]
        label = ", ".join(group)
        print(f"\n{'=' * 74}\n  [{i}/{len(groups)}] {label}\n{'=' * 74}", flush=True)

        with engine.begin() as conn:
            deleted = conn.execute(text(
                "DELETE FROM web_battery_validation WHERE upper(make_n) = ANY(:mk)"
            ), {"mk": g_upper}).rowcount
        print(f"  Cleared {deleted:,} existing rows", flush=True)

        started = time.monotonic()
        stats = web_battery_validate.main(
            enabled_makes=group,
            log_callback=_quiet,
            phase=args.phase,
            min_year=args.min_year,
        )
        elapsed = time.monotonic() - started

        with engine.connect() as conn:
            # Count web_battery_staging, NOT web_battery_validation: main() writes
            # scrape results to staging for review, and they only reach master when
            # an admin commits. Counting master made a working run report "0 rows"
            # for every make and hid that staging was being wiped between makes.
            final = conn.execute(text(
                "SELECT count(*) FROM web_battery_staging WHERE upper(make_n) = ANY(:mk)"
            ), {"mk": g_upper}).scalar()
            spend = dict(conn.execute(text(
                "SELECT provider, max(calls_made) FROM api_usage_quota"
                " WHERE provider IN ('brave','tavily') GROUP BY provider")).fetchall())

        print(f"\n  [{label}] done in {elapsed/60:.1f} min — {final:,} rows", flush=True)
        print(f"    stats : {stats}", flush=True)
        print(f"    spend : brave={spend.get('brave', 0)} tavily={spend.get('tavily', 0)}",
              flush=True)

    print(f"\n  ALL DONE in {(time.monotonic() - started_all)/60:.1f} min\n")


if __name__ == "__main__":
    main()
