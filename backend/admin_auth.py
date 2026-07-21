"""
admin_auth.py — Authentication helpers for the admin dashboard.

Session flow
------------
1. POST /api/admin/login   → verify bcrypt hash, create AdminSession row,
                             set HttpOnly + Secure + SameSite=Strict cookie.
2. Every protected route   → require_admin() reads cookie, looks up session
                             in DB, checks expiry, returns AdminUser.
3. POST /api/admin/logout  → deletes session row, clears cookie.

Account lifecycle (see admin_router.py for the routes themselves)
-------------------------------------------------------------------
- First admin: POST /api/admin/bootstrap, gated by both an empty
  admin_users table AND a shared-secret ADMIN_BOOTSTRAP_TOKEN.
- Additional admins: POST /api/admin/users, requires an already
  logged-in admin (require_admin) — no token needed, the login itself
  is the gate.
- Forgot/reset password: POST /api/admin/forgot-password issues a
  short-lived reset token (generate_reset_token below) either emailed
  via SES or handed to an admin as a shareable link
  (POST /api/admin/users/{id}/reset-link); POST /api/admin/reset-password
  consumes it (consume_reset_token) and invalidates every existing
  session for that admin (invalidate_all_sessions).

Security properties
-------------------
- Passwords stored as bcrypt hashes (cost factor 12).
- Session tokens and reset tokens are both 32 random bytes encoded as
  64-char hex strings (secrets.token_hex) — reset tokens are stored as
  a SHA-256 hash rather than bcrypt (see the comment above
  generate_reset_token for why that's correct, not a shortcut).
- Sessions expire after SESSION_TTL_HOURS (default 8); reset tokens
  expire after RESET_TOKEN_TTL_MINUTES (default 60).
- HttpOnly cookie prevents JavaScript access (XSS mitigation).
- SameSite=Strict blocks CSRF from cross-origin requests.
- Login/bootstrap/forgot-password/reset-password are all rate-limited
  in admin_router.py.
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


def invalidate_all_sessions(db: Session, admin: AdminUser) -> None:
    """
    Delete every AdminSession row for *admin* — used after a password
    reset so a changed credential actually forces re-login everywhere,
    not just on the device that made the change. Shared helper (not
    inlined in the reset-password route) so any future "change my own
    password while logged in" feature gets the same behavior for free.
    """
    db.query(AdminSession).filter(AdminSession.admin_id == admin.id).delete()
    db.commit()


# ---------------------------------------------------------------------------
# Password-reset token helpers
# ---------------------------------------------------------------------------
#
# Tokens are high-entropy CSPRNG output (secrets.token_hex(32), same
# generator as session tokens), not human-chosen secrets — unlike
# passwords, they don't need bcrypt's deliberately-slow hashing to resist
# offline brute force (256 bits of entropy is already infeasible to guess
# regardless of hash speed). A fast, unsalted SHA-256 of the token is the
# standard approach for this class of secret (this is how Django/Rails/
# Devise all do password-reset tokens) — do not "fix" this into bcrypt.

RESET_TOKEN_TTL_MINUTES: int = 60


def generate_reset_token(db: Session, admin: AdminUser) -> str:
    """
    Create a new password-reset token for *admin*, store only its hash,
    and return the raw token for the caller to embed in a URL or email.

    Overwrites any token already outstanding for this admin — that's
    intentional. Only the most-recently-issued token should ever be
    valid; do not extend this to support multiple simultaneously-valid
    tokens per admin.
    """
    token = _generate_token()
    admin.reset_token_hash = hashlib.sha256(token.encode()).hexdigest()
    admin.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
    db.commit()
    return token


def consume_reset_token(db: Session, token: str) -> Optional[AdminUser]:
    """
    Return the AdminUser matching *token* if it's valid and not expired,
    else None. Does NOT clear the token — the caller should only clear it
    (via clear_reset_token) once the new password has actually been
    validated and set, so a rejected weak-password attempt doesn't burn
    an otherwise-still-valid token.
    """
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    admin = db.query(AdminUser).filter(AdminUser.reset_token_hash == token_hash).first()
    if admin is None:
        return None
    if admin.reset_token_expires_at is None or datetime.now(timezone.utc) >= admin.reset_token_expires_at:
        return None
    return admin


def clear_reset_token(db: Session, admin: AdminUser) -> None:
    """Null out the reset-token columns after a successful reset."""
    admin.reset_token_hash = None
    admin.reset_token_expires_at = None
    db.commit()


# ---------------------------------------------------------------------------
# Bootstrap-token helper (first-admin setup — see POST /api/admin/bootstrap)
# ---------------------------------------------------------------------------

def verify_bootstrap_token(supplied: str) -> bool:
    """
    Constant-time comparison against ADMIN_BOOTSTRAP_TOKEN. An unset or
    empty env var always fails — a misconfigured empty token must never
    match an empty (or any) supplied value.
    """
    expected = os.environ.get("ADMIN_BOOTSTRAP_TOKEN", "")
    if not expected:
        return False
    return secrets.compare_digest(supplied, expected)


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