"""
Integration tests for admin bootstrap, forgot/reset-password, and the
Admin Users management routes, against the real local Postgres.

require_admin() (admin_auth.py) opens its own SessionLocal() rather than
taking a db session as a dependency, so it can't naturally join the
db_session fixture's rolled-back transaction the way routes using
Depends(get_db) do. real_auth_client works around this by monkeypatching
admin_auth.SessionLocal to hand back a close()-is-a-no-op wrapper around
db_session, so a real bootstrap -> login -> cookie -> protected-route
round trip inside one test stays inside that test's rolled-back
transaction instead of leaking committed rows into the dev database.

The bootstrap-race test is the one exception: real concurrency needs real
concurrent connections, which a single shared transaction can't provide,
so it runs against the live engine directly with manual cleanup via a
distinctive username prefix (mirroring _cleanup_verifytest_rows in
test_web_validate_staging_and_quota.py).
"""
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import admin_auth
import admin_router
from db import engine
from models import AdminAccountAuditLog, AdminUser

BOOTSTRAP_TOKEN = "test-bootstrap-token-xyz"


@pytest.fixture(autouse=True)
def _reset_limiter():
    admin_router._limiter.reset()
    yield
    admin_router._limiter.reset()


@pytest.fixture(autouse=True)
def _bootstrap_token_env(monkeypatch):
    monkeypatch.setenv("ADMIN_BOOTSTRAP_TOKEN", BOOTSTRAP_TOKEN)


class _NoCloseSessionWrapper:
    """Forwards everything to the wrapped session except close(), which
    is a no-op so require_admin() can't end the test's db_session early."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


@pytest.fixture()
def real_auth_client(db_session, monkeypatch):
    monkeypatch.setattr(admin_auth, "SessionLocal", lambda: _NoCloseSessionWrapper(db_session))
    test_app = FastAPI()
    test_app.include_router(admin_router.router)
    test_app.state.limiter = admin_router._limiter
    test_app.dependency_overrides[admin_router.get_db] = lambda: db_session
    with TestClient(test_app) as c:
        yield c


def _bootstrap(client, username="pytest_admin", password="supersecret1", token=BOOTSTRAP_TOKEN):
    return client.post("/api/admin/bootstrap", json={
        "username": username, "password": password, "bootstrap_token": token,
    })


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def test_bootstrap_status_reports_needs_setup_when_empty(real_auth_client):
    resp = real_auth_client.get("/api/admin/bootstrap/status")
    assert resp.status_code == 200
    assert resp.json()["needs_setup"] is True


def test_bootstrap_wrong_token_rejected(real_auth_client):
    resp = _bootstrap(real_auth_client, token="totally-wrong")
    assert resp.status_code == 401


def test_bootstrap_succeeds_once_then_blocks_regardless_of_token(real_auth_client):
    resp = _bootstrap(real_auth_client)
    assert resp.status_code == 200

    status = real_auth_client.get("/api/admin/bootstrap/status")
    assert status.json()["needs_setup"] is False

    # Second attempt 403s even with the CORRECT token — table-emptiness
    # is checked before the token comparison, so a populated table can
    # never be used as a token-guessing oracle.
    again = _bootstrap(real_auth_client, username="pytest_admin2")
    assert again.status_code == 403


def test_bootstrap_writes_audit_log_entry(real_auth_client, db_session):
    _bootstrap(real_auth_client)
    row = db_session.query(AdminAccountAuditLog).filter_by(action="bootstrap").first()
    assert row is not None
    assert row.target_username == "pytest_admin"
    assert row.actor_admin_id is None  # no authenticated actor for bootstrap


@pytest.fixture()
def _cleanup_bootstrap_race_rows():
    def _cleanup():
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM admin_account_audit_log WHERE target_username LIKE 'racetest_%'"))
            conn.execute(text("DELETE FROM admin_sessions WHERE admin_id IN (SELECT id FROM admin_users WHERE username LIKE 'racetest_%')"))
            conn.execute(text("DELETE FROM admin_users WHERE username LIKE 'racetest_%'"))
    _cleanup()
    yield
    _cleanup()


def test_bootstrap_concurrent_requests_only_create_one_admin(_cleanup_bootstrap_race_rows, monkeypatch):
    """The literal race the bootstrap design guards against: two
    near-simultaneous bootstrap calls must not both succeed. Needs real
    concurrent connections, so this runs against the live engine/app
    rather than the shared-transaction fixtures above."""
    monkeypatch.setenv("ADMIN_BOOTSTRAP_TOKEN", BOOTSTRAP_TOKEN)
    test_app = FastAPI()
    test_app.include_router(admin_router.router)
    test_app.state.limiter = admin_router._limiter
    admin_router._limiter.reset()

    results = []
    results_lock = threading.Lock()

    def worker(i):
        with TestClient(test_app) as c:
            resp = c.post("/api/admin/bootstrap", json={
                "username": f"racetest_{i}", "password": "supersecret1", "bootstrap_token": BOOTSTRAP_TOKEN,
            })
        with results_lock:
            results.append(resp.status_code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(200) == 1, f"expected exactly one successful bootstrap, got statuses: {results}"

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM admin_users WHERE username LIKE 'racetest_%'")).scalar()
    assert count == 1


# ---------------------------------------------------------------------------
# Forgot password
# ---------------------------------------------------------------------------

def test_forgot_password_identical_response_for_unknown_username(real_auth_client):
    _bootstrap(real_auth_client)
    resp = real_auth_client.post("/api/admin/forgot-password", json={"username": "does-not-exist"})
    assert resp.status_code == 200
    assert resp.json() == {"detail": "If that account exists, a reset link has been sent."}


def test_forgot_password_identical_response_when_known_but_no_email(real_auth_client):
    _bootstrap(real_auth_client)
    resp_known = real_auth_client.post("/api/admin/forgot-password", json={"username": "pytest_admin"})
    resp_unknown = real_auth_client.post("/api/admin/forgot-password", json={"username": "nope"})
    assert resp_known.status_code == resp_unknown.status_code == 200
    assert resp_known.json() == resp_unknown.json()


def test_forgot_password_generates_token_when_email_present(real_auth_client, db_session):
    _bootstrap(real_auth_client)
    admin = db_session.query(AdminUser).filter_by(username="pytest_admin").first()
    admin.email = "pytest@example.com"
    db_session.commit()

    real_auth_client.post("/api/admin/forgot-password", json={"username": "pytest_admin"})
    db_session.refresh(admin)
    assert admin.reset_token_hash is not None
    assert admin.reset_token_expires_at is not None


# ---------------------------------------------------------------------------
# Reset password
# ---------------------------------------------------------------------------

def test_reset_password_rejects_invalid_token(real_auth_client):
    resp = real_auth_client.post("/api/admin/reset-password", json={"token": "garbage", "new_password": "newpassword1"})
    assert resp.status_code == 400


def test_reset_password_rejects_expired_token(real_auth_client, db_session):
    _bootstrap(real_auth_client)
    admin = db_session.query(AdminUser).filter_by(username="pytest_admin").first()
    token = admin_auth.generate_reset_token(db_session, admin)
    admin.reset_token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    resp = real_auth_client.post("/api/admin/reset-password", json={"token": token, "new_password": "newpassword1"})
    assert resp.status_code == 400


def test_reset_password_weak_password_does_not_burn_token(real_auth_client, db_session):
    _bootstrap(real_auth_client)
    admin = db_session.query(AdminUser).filter_by(username="pytest_admin").first()
    token = admin_auth.generate_reset_token(db_session, admin)

    weak = real_auth_client.post("/api/admin/reset-password", json={"token": token, "new_password": "weak"})
    assert weak.status_code == 422  # rejected by pydantic min_length before the route body runs

    strong = real_auth_client.post("/api/admin/reset-password", json={"token": token, "new_password": "strongpassword1"})
    assert strong.status_code == 200


def test_reset_password_token_is_single_use(real_auth_client, db_session):
    _bootstrap(real_auth_client)
    admin = db_session.query(AdminUser).filter_by(username="pytest_admin").first()
    token = admin_auth.generate_reset_token(db_session, admin)

    first = real_auth_client.post("/api/admin/reset-password", json={"token": token, "new_password": "strongpassword1"})
    assert first.status_code == 200

    second = real_auth_client.post("/api/admin/reset-password", json={"token": token, "new_password": "anotherpassword2"})
    assert second.status_code == 400


def test_reset_password_invalidates_existing_sessions(real_auth_client, db_session):
    _bootstrap(real_auth_client)
    login = real_auth_client.post("/api/admin/login", json={"username": "pytest_admin", "password": "supersecret1"})
    assert login.status_code == 200

    me_before = real_auth_client.get("/api/admin/me")
    assert me_before.status_code == 200

    admin = db_session.query(AdminUser).filter_by(username="pytest_admin").first()
    token = admin_auth.generate_reset_token(db_session, admin)
    reset = real_auth_client.post("/api/admin/reset-password", json={"token": token, "new_password": "strongpassword1"})
    assert reset.status_code == 200

    me_after = real_auth_client.get("/api/admin/me")
    assert me_after.status_code == 401


# ---------------------------------------------------------------------------
# Admin Users CRUD
# ---------------------------------------------------------------------------

def test_admin_users_requires_authentication(real_auth_client):
    resp = real_auth_client.get("/api/admin/users")
    assert resp.status_code == 401


def _bootstrap_and_login(client, username="pytest_admin", password="supersecret1"):
    _bootstrap(client, username=username, password=password)
    resp = client.post("/api/admin/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return client


def test_create_admin_user_duplicate_username_and_email_409(real_auth_client):
    _bootstrap_and_login(real_auth_client)

    ok = real_auth_client.post("/api/admin/users", json={
        "username": "pytest_admin2", "password": "supersecret2", "email": "second@example.com",
    })
    assert ok.status_code == 201

    dup_username = real_auth_client.post("/api/admin/users", json={
        "username": "pytest_admin2", "password": "supersecret3",
    })
    assert dup_username.status_code == 409

    dup_email = real_auth_client.post("/api/admin/users", json={
        "username": "pytest_admin3", "password": "supersecret3", "email": "second@example.com",
    })
    assert dup_email.status_code == 409


def test_patch_email_is_self_only(real_auth_client):
    _bootstrap_and_login(real_auth_client)
    other = real_auth_client.post("/api/admin/users", json={"username": "pytest_admin2", "password": "supersecret2"})
    other_id = other.json()["id"]

    cross_edit = real_auth_client.patch(f"/api/admin/users/{other_id}", json={"email": "hijack@example.com"})
    assert cross_edit.status_code == 403

    me = real_auth_client.get("/api/admin/me").json()
    users = real_auth_client.get("/api/admin/users").json()["users"]
    own_id = next(u["id"] for u in users if u["username"] == me["username"])
    self_edit = real_auth_client.patch(f"/api/admin/users/{own_id}", json={"email": "self@example.com"})
    assert self_edit.status_code == 200


def test_delete_admin_blocks_self(real_auth_client):
    _bootstrap_and_login(real_auth_client)
    me = real_auth_client.get("/api/admin/me").json()
    users = real_auth_client.get("/api/admin/users").json()["users"]
    own_id = next(u["id"] for u in users if u["username"] == me["username"])

    resp = real_auth_client.delete(f"/api/admin/users/{own_id}")
    assert resp.status_code == 400


def test_delete_admin_allows_a_legitimate_two_to_one_deletion(real_auth_client):
    _bootstrap_and_login(real_auth_client)
    other = real_auth_client.post("/api/admin/users", json={"username": "pytest_admin2", "password": "supersecret2"})
    other_id = other.json()["id"]

    # 2 admins exist — deleting one down to 1 must be allowed (only
    # deleting the LAST admin should ever be blocked).
    resp = real_auth_client.delete(f"/api/admin/users/{other_id}")
    assert resp.status_code == 200


def test_generate_reset_link_for_another_admin(real_auth_client):
    _bootstrap_and_login(real_auth_client)
    other = real_auth_client.post("/api/admin/users", json={"username": "pytest_admin2", "password": "supersecret2"})
    other_id = other.json()["id"]

    resp = real_auth_client.post(f"/api/admin/users/{other_id}/reset-link")
    assert resp.status_code == 200
    assert "token" in resp.json()


def test_audit_log_records_lifecycle_actions(real_auth_client):
    _bootstrap_and_login(real_auth_client)
    other = real_auth_client.post("/api/admin/users", json={"username": "pytest_admin2", "password": "supersecret2"})
    other_id = other.json()["id"]
    real_auth_client.post(f"/api/admin/users/{other_id}/reset-link")
    real_auth_client.delete(f"/api/admin/users/{other_id}")

    resp = real_auth_client.get("/api/admin/users/audit-log")
    assert resp.status_code == 200
    actions = {row["action"] for row in resp.json()["items"]}
    assert actions == {"bootstrap", "create", "reset_link_generated", "delete"}


def test_audit_log_survives_deleted_admin_via_username_snapshot(real_auth_client):
    _bootstrap_and_login(real_auth_client)
    other = real_auth_client.post("/api/admin/users", json={"username": "pytest_admin2", "password": "supersecret2"})
    other_id = other.json()["id"]
    real_auth_client.delete(f"/api/admin/users/{other_id}")

    resp = real_auth_client.get("/api/admin/users/audit-log")
    delete_row = next(r for r in resp.json()["items"] if r["action"] == "delete")
    assert delete_row["target_username"] == "pytest_admin2"


# ---------------------------------------------------------------------------
# Email-failure path
# ---------------------------------------------------------------------------

def test_forgot_password_response_unaffected_by_email_send_failure(real_auth_client, db_session, monkeypatch):
    # send_reset_email() is designed to never raise (see email_utils.py) —
    # its real failure mode is returning False (SES unconfigured or the
    # SES call itself failing). The route must still 200 with the generic
    # message, and the token must still have been generated, so the
    # admin-generated-link fallback keeps working even if SES is broken.
    monkeypatch.setattr(admin_router, "send_reset_email", lambda *a, **k: False)

    _bootstrap(real_auth_client)
    admin = db_session.query(AdminUser).filter_by(username="pytest_admin").first()
    admin.email = "pytest@example.com"
    db_session.commit()

    resp = real_auth_client.post("/api/admin/forgot-password", json={"username": "pytest_admin"})
    assert resp.status_code == 200
    assert resp.json() == {"detail": "If that account exists, a reset link has been sent."}

    db_session.refresh(admin)
    assert admin.reset_token_hash is not None
