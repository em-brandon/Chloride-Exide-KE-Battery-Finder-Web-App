"""
Integration test for the public, unauthenticated GET /health route — the ALB
target-group check should get a plain 200 without needing admin credentials,
and only a minimal body (no pool/latency diagnostics, unlike the admin-gated
GET /api/admin/health).
"""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module


def test_health_endpoint_requires_no_auth_and_returns_minimal_body():
    # Mount only the /health route (not the full app) to avoid app.py's
    # lifespan starting its self-rescheduling background timers.
    test_app = FastAPI()
    test_app.state.limiter = app_module.limiter
    test_app.add_api_route("/health", app_module.health_check, methods=["GET"])

    with TestClient(test_app) as c:
        resp = c.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
