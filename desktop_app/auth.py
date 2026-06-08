"""Direct DB authentication — no FastAPI needed."""
from __future__ import annotations

import sys
from pathlib import Path

# project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import SessionLocal
from models import AdminUser
from admin_auth import verify_password


def login(username: str, password: str) -> AdminUser | None:
    """Return AdminUser if credentials match, else None."""
    db = SessionLocal()
    try:
        user = db.query(AdminUser).filter(AdminUser.username == username).first()
        if user and verify_password(password, user.password_hash):
            return user
        return None
    finally:
        db.close()
