"""
admin_auth.py — Authentication helpers for the admin dashboard.

Session flow
------------
1. POST /api/admin/login   → verify bcrypt hash, create AdminSession row,
                             set HttpOnly + Secure + SameSite=Strict cookie.
2. Every protected route   → require_admin() reads cookie, looks up session
                             in DB, checks expiry, returns AdminUser.
3. POST /api/admin/logout  → deletes session row, clears cookie.

Security properties
-------------------
- Passwords stored as bcrypt hashes (cost factor 12).
- Session tokens are 32 random bytes encoded as 64-char hex strings.
- Sessions expire after SESSION_TTL_HOURS (default 8).
- HttpOnly cookie prevents JavaScript access (XSS mitigation).
- SameSite=Strict blocks CSRF from cross-origin requests.
- Login endpoint is rate-limited (5/minute) in admin_router.py.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Cookie, HTTPException, Request
from sqlalchemy.orm import Session

from db import SessionLocal
from models import AdminSession, AdminUser

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SESSION_TTL_HOURS: int = 8
COOKIE_NAME: str = "admin_session"
_IS_SECURE: bool = os.environ.get("ADMIN_COOKIE_SECURE", "true").lower() != "false"


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain* at cost factor 12."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed*."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _generate_token() -> str:
    """Return a 64-character cryptographically random hex string."""
    return secrets.token_hex(32)


def create_session(db: Session, admin: AdminUser, ip_address: Optional[str]) -> str:
    """
    Insert a new AdminSession row and return the raw session token.
    The caller is responsible for setting the cookie on the response.
    """
    token = _generate_token()
    now = datetime.now(timezone.utc)
    session = AdminSession(
        session_token=token,
        admin_id=admin.id,
        created_at=now,
        expires_at=now + timedelta(hours=SESSION_TTL_HOURS),
        ip_address=ip_address,
    )
    db.add(session)
    db.commit()
    return token


def _lookup_session(db: Session, token: str) -> Optional[tuple[AdminSession, AdminUser]]:
    """Return (session, user) if the token is valid and not expired, else None."""
    session = (
        db.query(AdminSession)
        .filter(AdminSession.session_token == token)
        .first()
    )
    if session is None:
        return None
    if datetime.now(timezone.utc) >= session.expires_at:
        db.delete(session)
        db.commit()
        return None
    user = db.query(AdminUser).filter(AdminUser.id == session.admin_id).first()
    if user is None:
        return None
    return session, user


def delete_session(db: Session, token: str) -> None:
    """Delete a session by token (logout / manual revocation)."""
    session = db.query(AdminSession).filter(AdminSession.session_token == token).first()
    if session:
        db.delete(session)
        db.commit()


# ---------------------------------------------------------------------------
# FastAPI dependency — use as: admin: AdminUser = Depends(require_admin)
# ---------------------------------------------------------------------------

def require_admin(request: Request) -> AdminUser:
    """
    FastAPI dependency that enforces admin authentication.

    Reads the HttpOnly session cookie, validates against the DB,
    and returns the AdminUser.  Raises HTTP 401 on any failure so
    the frontend can redirect to /admin/login.
    """
    token: Optional[str] = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    db: Session = SessionLocal()
    try:
        result = _lookup_session(db, token)
    finally:
        db.close()

    if result is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    _session, user = result
    return user


# ---------------------------------------------------------------------------
# Cookie helpers (used by login / logout routes)
# ---------------------------------------------------------------------------

def set_session_cookie(response, token: str) -> None:
    """Attach the HttpOnly session cookie to *response*."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_IS_SECURE,
        samesite="strict",
        max_age=SESSION_TTL_HOURS * 3600,
        path="/",
    )


def clear_session_cookie(response) -> None:
    """Remove the session cookie from *response*."""
    response.delete_cookie(key=COOKIE_NAME, path="/")
