"""
Integration tests for the web-validate pipeline's concurrency guards
against the real local Postgres. All of these routes take
admin: AdminUser = Depends(require_admin) (and some also db: Session =
Depends(get_db)), so they run through the standard client/db_session
fixtures — no manual DB seeding needed for the guards themselves.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import admin_router


@pytest.fixture(autouse=True)
def _reset_pipeline_state():
    """admin_router._pipeline_state is process-global — reset it around
    every test in this file so tests don't leak "running"/"paused" state
    into each other or into unrelated test files."""
    original = dict(admin_router._pipeline_state)
    yield
    admin_router._pipeline_state.clear()
    admin_router._pipeline_state.update(original)


def test_run_web_validate_blocked_while_paused(client):
    admin_router._pipeline_state["status"] = "paused"
    resp = client.post("/api/admin/pipeline/web-validate/run", json={})
    assert resp.status_code == 409


def test_run_web_validate_blocked_while_running(client):
    admin_router._pipeline_state["status"] = "running"
    resp = client.post("/api/admin/pipeline/web-validate/run", json={})
    assert resp.status_code == 409


def test_reset_cache_blocked_while_paused(client):
    admin_router._pipeline_state["status"] = "paused"
    resp = client.post("/api/admin/pipeline/web-validate/reset-cache")
    assert resp.status_code == 409


def test_reset_cache_blocked_while_running(client):
    admin_router._pipeline_state["status"] = "running"
    resp = client.post("/api/admin/pipeline/web-validate/reset-cache")
    assert resp.status_code == 409


def test_reset_cache_allowed_while_idle(client):
    admin_router._pipeline_state["status"] = "idle"
    resp = client.post("/api/admin/pipeline/web-validate/reset-cache")
    assert resp.status_code == 200


def test_commit_staging_blocked_while_pipeline_running(client, db_session):
    admin_router._pipeline_state["status"] = "running"
    resp = client.post("/api/admin/pipeline/web-validate/staging/commit", json={})
    assert resp.status_code == 409


def test_discard_staging_blocked_while_pipeline_paused(client, db_session):
    admin_router._pipeline_state["status"] = "paused"
    resp = client.post("/api/admin/pipeline/web-validate/staging/discard")
    assert resp.status_code == 409
