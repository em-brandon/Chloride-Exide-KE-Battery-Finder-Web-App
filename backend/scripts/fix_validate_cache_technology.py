"""
fix_validate_cache_technology.py
--------------------------------
Correct the `technology` field of cached rows in
cache/battery_validate_cache.json to match the battery each row actually
resolved to.

WHY THE CACHE NEEDS THIS SEPARATELY
-----------------------------------
_resolve_battery_code() used to return the technology scraped from search
text rather than the technology of the battery _select_batteries() actually
returned, which contradicted battery_code on ~40% of web_battery_validation
rows. That is fixed at source now — but web_battery_validate.py's Phase 2
appends a file-cache hit straight to the output buffer without re-resolving
it, so a rebuild would replay the old wrong values verbatim and the fix
would have no visible effect.

Clearing the cache instead would work, but costs a full re-fetch (~15,000
lookups) to arrive at the same Ah values, since the search query is built
only from make/model/year and none of those changed. Correcting in place is
equivalent for the technology defect and instant.

Every cached battery_code resolves in battery_specs (verified: 15,588 of
15,588), so the correction is complete rather than best-effort.

Usage (run from backend/)
-------------------------
    python scripts/fix_validate_cache_technology.py
    python scripts/fix_validate_cache_technology.py --execute
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

from sqlalchemy import text

from db import engine

CACHE_FILE = os.path.join(ROOT, "cache", "battery_validate_cache.json")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true", help="Apply. Default is a dry run.")
    p.add_argument("--cache-file", default=CACHE_FILE)
    args = p.parse_args()

    with engine.connect() as conn:
        specs = {r[0]: r[1] for r in conn.execute(text(
            "SELECT battery_code, technology FROM battery_specs"
            " WHERE deleted_at IS NULL")).fetchall()}
    print(f"battery_specs codes loaded : {len(specs)}")

    with open(args.cache_file, encoding="utf-8") as fh:
        cache = json.load(fh)
    print(f"cache entries              : {len(cache)}")

    total = agree = fixed = unmatched = 0
    changes = Counter()
    for key, row in cache.items():
        if not row:
            continue
        total += 1
        code = row.get("battery_code")
        real = specs.get(code)
        if real is None:
            unmatched += 1
            continue
        cur = (row.get("technology") or "").upper()
        if cur == real.upper():
            agree += 1
            continue
        changes[f"{cur or '-'} -> {real}"] += 1
        fixed += 1
        if args.execute:
            row["technology"] = real

    print(f"\nnon-null rows              : {total}")
    print(f"  already correct          : {agree}")
    print(f"  corrected                : {fixed}")
    print(f"  battery_code not in specs: {unmatched}")
    print("\nchanges by transition:")
    for k, n in changes.most_common():
        print(f"  {k:<22} {n:>6}")

    if not args.execute:
        print("\n[DRY RUN] Cache not modified. Re-run with --execute to apply.\n")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = f"{args.cache_file}.{stamp}.bak"
    shutil.copy2(args.cache_file, backup)
    with open(args.cache_file, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False)
    print(f"\n  DONE — {fixed:,} entries corrected")
    print(f"  Backup of the previous cache: {backup}\n")


if __name__ == "__main__":
    main()
