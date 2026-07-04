"""
create_admin.py — CLI script to bootstrap the first admin user.

Usage
-----
    python create_admin.py --username admin --password yourpassword

Run this once after `alembic upgrade head` to create the initial admin account.
Safe to re-run — will error if the username already exists rather than
silently overwriting the password.

To change a password, use --force:
    python create_admin.py --username admin --password newpassword --force
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

# Ensure project root is on path when run from scripts/
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from admin_auth import hash_password
from db import SessionLocal
from models import AdminUser


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an admin dashboard user.")
    parser.add_argument("--username", required=True, help="Admin username (max 100 chars)")
    parser.add_argument("--password", required=True, help="Plain-text password (will be hashed)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="If the username already exists, update its password instead of erroring",
    )
    args = parser.parse_args()

    if len(args.username) > 100:
        print("ERROR: username must be 100 characters or fewer.", file=sys.stderr)
        sys.exit(1)

    if len(args.password) < 8:
        print("ERROR: password must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)

    hashed = hash_password(args.password)

    db = SessionLocal()
    try:
        existing = db.query(AdminUser).filter(AdminUser.username == args.username).first()

        if existing:
            if not args.force:
                print(
                    f"ERROR: Admin user {args.username!r} already exists. "
                    "Use --force to update the password.",
                    file=sys.stderr,
                )
                sys.exit(1)
            existing.password_hash = hashed
            db.commit()
            print(f"[create_admin] Password updated for {args.username!r}.")
        else:
            user = AdminUser(
                username=args.username,
                password_hash=hashed,
                created_at=datetime.now(timezone.utc),
            )
            db.add(user)
            db.commit()
            print(f"[create_admin] Admin user {args.username!r} created successfully.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
