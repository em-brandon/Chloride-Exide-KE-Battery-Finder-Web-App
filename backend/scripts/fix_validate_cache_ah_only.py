"""
fix_validate_cache_ah_only.py
-----------------------------
Re-resolve every cached battery_code/technology in
cache/battery_validate_cache.json using Ah alone, so the whole cache matches
the rule _resolve_battery_code() now applies.

WHY THIS IS NEEDED
------------------
_resolve_battery_code() used to pass the web-scraped technology into
_select_batteries() as a *preference*, so the scraped AGM/EFB keyword
influenced which battery was picked. It no longer does — technology is now
resolved purely by catalogue rules (_TECH_PRIORITY, imported stock first)
and availability at the Ah figure.

That change only affects newly-resolved combos. web_battery_validate.py's
Phase 2 appends a file-cache hit straight to the output buffer without
re-resolving it, so 15,588 cached entries would keep battery codes chosen
under the old preference rule while fresh rows used the new one — the same
split-brain the technology fix ran into, and the reason
fix_validate_cache_technology.py exists.

Re-resolution here is a pure catalogue lookup: region comes from the make,
the battery comes from the Ah. No network calls, no re-fetching, instant.
Ah itself is never changed — it is the one figure that genuinely came from
the web.

Run this with the pipeline STOPPED. web_battery_validate.py rewrites this
file periodically, so a concurrent run would race the save.

Usage (run from backend/)
-------------------------
    python scripts/fix_validate_cache_ah_only.py
    python scripts/fix_validate_cache_ah_only.py --execute
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from matcher import (_infer_stop_start, _make_region, _norm_fuel, _preferred_tech,
                     _select_batteries)

CACHE_FILE = os.path.join(ROOT, "cache", "battery_validate_cache.json")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true", help="Apply. Default is a dry run.")
    p.add_argument("--cache-file", default=CACHE_FILE)
    args = p.parse_args()

    with open(args.cache_file, encoding="utf-8") as fh:
        cache = json.load(fh)
    print(f"cache entries        : {len(cache):,}")

    total = unchanged = code_changed = tech_changed = failed = 0
    tech_moves = Counter()
    examples: list[str] = []

    for row in cache.values():
        if not row:
            continue
        ah = row.get("ah")
        make_n = row.get("make_n")
        if ah is None or not make_n:
            continue
        total += 1
        # Identical rule to _resolve_battery_code(): technology from the
        # _preferred_tech() rules engine (never the scraped keyword), then
        # catalogue availability at this Ah. stop_start=True matches the API
        # default. Ah itself is never touched.
        fuel = row.get("fuel_type")
        norm_fuel = _norm_fuel(fuel) if fuel else ""
        year = row.get("year")
        try:
            pref_tech = _preferred_tech(
                row.get("engine_cc") or 0,
                norm_fuel,
                year,
                make_n,
                _infer_stop_start(make_n, year, norm_fuel),
            )
            primary, _ = _select_batteries(ah, pref_tech, _make_region(make_n))
        except Exception:
            failed += 1
            continue

        new_code, new_tech = primary["battery_code"], primary["technology"]
        old_code = row.get("battery_code")
        old_tech = (row.get("technology") or "").upper()

        if old_code == new_code and old_tech == new_tech.upper():
            unchanged += 1
            continue
        if old_code != new_code:
            code_changed += 1
            if len(examples) < 8:
                examples.append(
                    f"    {make_n} {row.get('model_n','')[:28]:<28} {ah:>3}Ah  "
                    f"{old_code}  ->  {new_code}")
        if old_tech != new_tech.upper():
            tech_changed += 1
            tech_moves[f"{old_tech or '-'} -> {new_tech}"] += 1

        if args.execute:
            row["battery_code"] = new_code
            row["technology"] = new_tech

    print(f"\nresolvable rows      : {total:,}")
    print(f"  already correct    : {unchanged:,}")
    print(f"  battery_code moved : {code_changed:,}")
    print(f"  technology moved   : {tech_changed:,}")
    print(f"  resolve failed     : {failed:,}")

    if tech_moves:
        print("\ntechnology transitions:")
        for k, n in tech_moves.most_common():
            print(f"  {k:<18} {n:>6}")
    if examples:
        print("\nsample battery_code changes:")
        for line in examples:
            print(line)

    if not args.execute:
        print("\n[DRY RUN] Cache not modified. Re-run with --execute to apply.\n")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = f"{args.cache_file}.{stamp}.bak"
    shutil.copy2(args.cache_file, backup)
    with open(args.cache_file, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False)
    print(f"\n  DONE — {code_changed:,} codes and {tech_changed:,} technologies re-resolved")
    print(f"  Backup of the previous cache: {backup}\n")


if __name__ == "__main__":
    main()
