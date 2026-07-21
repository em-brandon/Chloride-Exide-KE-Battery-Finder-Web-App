"""
Shared pytest fixtures.

Integration tests run against the real local Postgres (docker-compose,
DATABASE_URL from .env) rather than sqlite/mocks — this repo already treats
that database as the source of truth for schema behavior (see CLAUDE.md).
Each test gets its own transaction that is rolled back afterwards, so tests
never leave data behind in the shared dev database.

Admin routes are exercised against a minimal FastAPI app that only mounts
admin_router's router — not the full backend/app.py — so tests don't trigger
app.py's lifespan (which starts self-rescheduling, non-daemon
threading.Timer chains for the read-counter flush / midnight reset that
would otherwise keep the pytest process alive indefinitely).
"""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import admin_router
from db import engine
from models import AdminUser


@pytest.fixture()
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        # A test that hits a route causing an unhandled DB error (e.g. an
        # IntegrityError) can leave the connection's transaction already
        # rolled back internally by SQLAlchemy before teardown gets here.
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture()
def public_db_session(db_session):
    """
    A session for exercising code paths that use db.PublicSessionLocal
    (app.py's public routes, app_state.py, matcher.py's write-adjacent
    reads) against the same rolled-back transaction as db_session, rather
    than PublicSessionLocal's real pool — which is bound to the separate
    batteryfinder_public role/connection and would leak rows into the dev
    database on commit, since it can't join db_session's transaction.
    Tests should monkeypatch the relevant module's PublicSessionLocal
    reference to `lambda: public_db_session` (mirroring how `client` overrides
    admin_router.get_db with db_session).
    """
    return db_session


@pytest.fixture()
def fake_admin():
    admin = AdminUser()
    admin.id = 0
    admin.username = "test-admin"
    return admin


@pytest.fixture()
def client(db_session, fake_admin):
    test_app = FastAPI()
    test_app.include_router(admin_router.router)
    test_app.state.limiter = admin_router._limiter

    test_app.dependency_overrides[admin_router.get_db] = lambda: db_session
    test_app.dependency_overrides[admin_router.require_admin] = lambda: fake_admin

    with TestClient(test_app) as c:
        yield c
