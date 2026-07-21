"""
remove_atlas_ultrapower.py
--------------------------
Soft-deletes rows from battery_specs where battery_code contains
'ATLAS' or 'ULTRAPOWER' (case-insensitive).

Sets deleted_at = now() rather than hard-deleting so the audit history
is preserved. Re-running is safe — already-deleted rows are skipped.
"""

import sys
from datetime import datetime, timezone

from sqlalchemy import text

sys.path.insert(0, ".")
from db import engine


BRANDS = ("ATLAS", "ULTRAPOWER")

_LIKE_CLAUSES = " OR ".join(
    f"UPPER(battery_code) LIKE '%{b}%'" for b in BRANDS
)

SELECT_SQL = text(
    f"SELECT battery_code, model_key, ah, technology"
    f" FROM battery_specs"
    f" WHERE deleted_at IS NULL AND ({_LIKE_CLAUSES})"
)

DELETE_SQL = text(
    f"UPDATE battery_specs SET deleted_at = :now"
    f" WHERE deleted_at IS NULL AND ({_LIKE_CLAUSES})"
)


def main() -> None:
    with engine.begin() as conn:
        rows = conn.execute(SELECT_SQL).fetchall()

        if not rows:
            print("No ATLAS or ULTRAPOWER batteries found in active battery_specs.")
            return

        print(f"Found {len(rows)} active row(s) to soft-delete:\n")
        for r in rows:
            print(f"  {r[0]:<35}  model_key={r[1]:<20}  {r[2]}Ah  {r[3]}")

        now = datetime.now(timezone.utc)
        result = conn.execute(DELETE_SQL, {"now": now})
        print(f"\nDone. {result.rowcount} row(s) soft-deleted (deleted_at = {now.isoformat()}).")
        print("Use the admin dashboard's 'Refresh Matcher Cache' action or restart the app to refresh the in-memory battery cache.")


if __name__ == "__main__":
    main()
