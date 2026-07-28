"""
Tests for the OEM Fitment "brand grid" backend support: the per-make
aggregation endpoint (GET /vehicle-data/oem-fitment/by-make) and the
exact-match `make` filter added to the existing paginated
GET /vehicle-data/oem-fitment endpoint.

Both routes read via `with engine.connect() as conn:` (raw engine), not
Depends(get_db) — like the rest of oem_fitment's admin routes — so they
can't see db_session's uncommitted test transaction. Seed/clean up
directly against the real dev DB with a distinctive 'VERIFYTEST' marker,
mirroring test_web_validate_staging_and_quota.py's _cleanup_verifytest_rows
pattern.
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import engine

_MAKE_A = "VERIFYTEST MAKE A"
_MAKE_B = "VERIFYTEST MAKE B"


@pytest.fixture()
def _cleanup_verifytest_fitment():
    def _cleanup():
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM oem_fitment WHERE make LIKE 'VERIFYTEST%'"))
    _cleanup()
    yield
    _cleanup()


def _seed_row(make, model, year_from, year_to, ah=50.0):
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO oem_fitment (vehicle_category, make, model, year_from, year_to, ah, technology)"
            " VALUES ('passenger', :make, :model, :yf, :yt, :ah, 'MF')"
        ), {"make": make, "model": model, "yf": year_from, "yt": year_to, "ah": ah})


def test_by_make_aggregates_counts_and_year_range(client, _cleanup_verifytest_fitment):
    _seed_row(_MAKE_A, "MODEL ONE", 2010, 2015)
    _seed_row(_MAKE_A, "MODEL ONE", 2016, None)   # same model, different tier — not a new model
    _seed_row(_MAKE_A, "MODEL TWO", 2018, 2020)
    _seed_row(_MAKE_B, "MODEL THREE", 2005, 2009)

    resp = client.get("/api/admin/vehicle-data/oem-fitment/by-make")
    assert resp.status_code == 200
    by_make = {m["make"]: m for m in resp.json()["makes"]}

    assert by_make[_MAKE_A]["model_count"] == 2
    assert by_make[_MAKE_A]["row_count"] == 3
    assert by_make[_MAKE_A]["year_min"] == 2010
    assert by_make[_MAKE_A]["year_max"] == 2020

    assert by_make[_MAKE_B]["model_count"] == 1
    assert by_make[_MAKE_B]["row_count"] == 1
    assert by_make[_MAKE_B]["year_min"] == 2005
    assert by_make[_MAKE_B]["year_max"] == 2009


def test_oem_fitment_exact_make_filter_excludes_other_makes(client, _cleanup_verifytest_fitment):
    _seed_row(_MAKE_A, "MODEL ONE", 2010, 2015)
    _seed_row(_MAKE_B, "MODEL TWO", 2010, 2015)

    resp = client.get("/api/admin/vehicle-data/oem-fitment", params={"make": _MAKE_A})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert all(item["make"] == _MAKE_A for item in body["items"])


def test_oem_fitment_make_filter_is_exact_not_substring(client, _cleanup_verifytest_fitment):
    # A model containing the other make's name as a substring must not leak
    # through the exact `make` filter.
    _seed_row(_MAKE_A, "MODEL ONE", 2010, 2015)
    _seed_row(_MAKE_B, f"{_MAKE_A} EDITION", 2010, 2015)

    resp = client.get("/api/admin/vehicle-data/oem-fitment", params={"make": _MAKE_A})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["model"] == "MODEL ONE"


def test_oem_fitment_and_by_make_require_admin():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import admin_router

    test_app = FastAPI()
    test_app.include_router(admin_router.router)
    test_app.state.limiter = admin_router._limiter
    with TestClient(test_app) as anon_client:
        assert anon_client.get("/api/admin/vehicle-data/oem-fitment").status_code in (401, 403)
        assert anon_client.get("/api/admin/vehicle-data/oem-fitment/by-make").status_code in (401, 403)
