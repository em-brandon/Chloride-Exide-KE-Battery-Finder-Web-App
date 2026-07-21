"""
Integration tests for the web-validate pipeline's staging lifecycle
(commit_staging/discard_staging/staging_pre_commit) and the pipeline-level
_upsert_rows/_try_reserve_quota functions, against the real local Postgres.

Two distinct DB-access patterns exist here, tested differently:
- commit_staging/discard_staging/staging_pre_commit use Depends(get_db),
  so they run through the client/db_session fixtures' rolled-back
  transaction like any other admin_router route — no manual cleanup needed.
- _upsert_rows/_try_reserve_quota (pipelines/web_battery_validate.py) take
  a raw engine and are called from a background thread, not a request —
  they can't join db_session's transaction, so those tests seed/clean up
  directly against the real dev DB using a distinctive 'VERIFYTEST' marker.
"""
import sys
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import engine
from pipelines.web_battery_validate import _upsert_rows, _try_reserve_quota


# ---------------------------------------------------------------------------
# Staging lifecycle (commit_staging / discard_staging / staging_pre_commit)
# — via client/db_session, safe to seed+assert directly since these routes
# now use Depends(get_db)
# ---------------------------------------------------------------------------

def _stage_row(db_session, run_id, make_n, model_n, year, battery_code, ah, technology,
                is_valid=True, conflict=False):
    db_session.execute(text(
        "INSERT INTO web_battery_staging"
        " (run_id, make_n, model_n, year, battery_code, ah, technology, source, is_valid, conflict)"
        " VALUES (:rid, :mn, :mo, :yr, :bc, :ah, :tech, 'test', :iv, :cf)"
    ), {"rid": run_id, "mn": make_n, "mo": model_n, "yr": year,
        "bc": battery_code, "ah": ah, "tech": technology, "iv": is_valid, "cf": conflict})
    db_session.commit()


def _seed_master(db_session, make_n, model_n, year, battery_code, ah, technology, run_id="old-run"):
    now = datetime.now(timezone.utc)
    db_session.execute(text(
        "INSERT INTO web_battery_validation"
        " (make_n, model_n, year, battery_code, ah, technology, source, validated_at, run_id)"
        " VALUES (:mn, :mo, :yr, :bc, :ah, :tech, 'test', :now, :rid)"
    ), {"mn": make_n, "mo": model_n, "yr": year, "bc": battery_code, "ah": ah,
        "tech": technology, "now": now, "rid": run_id})
    db_session.commit()


def test_commit_staging_added_vs_updated_change_type(client, db_session):
    """
    Regression test for the actual bug this branch exists to fix:
    commit_staging()'s change_type used to always resolve to "updated"
    because the scrape phase had already written the key into master
    before this ever ran. Now that scrape writes go into staging first,
    a genuinely new key must resolve to "added".
    """
    run_id = str(uuid.uuid4())
    _seed_master(db_session, "TESTMAKE", "EXISTING_MODEL", 2019, "OLD001", 55, "MF")
    _stage_row(db_session, run_id, "TESTMAKE", "EXISTING_MODEL", 2019, "NEW001", 60, "EFB")
    _stage_row(db_session, run_id, "TESTMAKE", "BRANDNEW_MODEL", 2022, "NEW002", 45, "MF")

    resp = client.post("/api/admin/pipeline/web-validate/staging/commit", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["committed"] == 2

    changelog = db_session.execute(text(
        "SELECT model_n, change_type, old_values FROM web_battery_validation_changelog"
        " WHERE version_id = :vid"
    ), {"vid": body["version_id"]}).fetchall()
    by_model = {r.model_n: r for r in changelog}

    assert by_model["EXISTING_MODEL"].change_type == "updated"
    assert by_model["EXISTING_MODEL"].old_values is not None

    assert by_model["BRANDNEW_MODEL"].change_type == "added"
    assert by_model["BRANDNEW_MODEL"].old_values is None


def test_commit_staging_invalid_row_removed_from_master(client, db_session):
    _seed_master(db_session, "TESTMAKE", "INVALID_MODEL", 2018, "OLD003", 50, "MF")
    run_id = str(uuid.uuid4())
    _stage_row(db_session, run_id, "TESTMAKE", "INVALID_MODEL", 2018, "NEW003", 999, "BOGUS", is_valid=False)

    resp = client.post("/api/admin/pipeline/web-validate/staging/commit", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["removed_invalid"] == 1
    assert body["committed"] == 0

    remaining = db_session.execute(text(
        "SELECT 1 FROM web_battery_validation WHERE make_n='TESTMAKE' AND model_n='INVALID_MODEL'"
    )).fetchone()
    assert remaining is None


def test_commit_staging_keep_current_resolution_leaves_master_untouched(client, db_session):
    _seed_master(db_session, "TESTMAKE", "CONFLICT_MODEL", 2020, "MASTER001", 55, "MF")
    run_id = str(uuid.uuid4())
    _stage_row(db_session, run_id, "TESTMAKE", "CONFLICT_MODEL", 2020, "STAGED001", 70, "AGM", conflict=True)

    resp = client.post("/api/admin/pipeline/web-validate/staging/commit", json={
        "conflict_resolutions": [
            {"make_n": "TESTMAKE", "model_n": "CONFLICT_MODEL", "year": 2020, "keep": "current"},
        ],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["committed"] == 0
    assert body["conflicts_resolved"] == 1

    row = db_session.execute(text(
        "SELECT battery_code FROM web_battery_validation WHERE make_n='TESTMAKE' AND model_n='CONFLICT_MODEL'"
    )).fetchone()
    assert row.battery_code == "MASTER001"


def test_discard_staging_does_not_touch_master(client, db_session):
    _seed_master(db_session, "TESTMAKE", "UNRELATED_MODEL", 2021, "KEEP001", 55, "MF")
    run_id = str(uuid.uuid4())
    _stage_row(db_session, run_id, "TESTMAKE", "TO_DISCARD", 2023, "DISCARD001", 50, "MF")

    resp = client.post("/api/admin/pipeline/web-validate/staging/discard")
    assert resp.status_code == 200
    assert resp.json()["discarded"] == 1

    staging_count = db_session.execute(text("SELECT COUNT(*) FROM web_battery_staging")).scalar()
    assert staging_count == 0

    master_row = db_session.execute(text(
        "SELECT battery_code FROM web_battery_validation WHERE make_n='TESTMAKE' AND model_n='UNRELATED_MODEL'"
    )).fetchone()
    assert master_row is not None and master_row.battery_code == "KEEP001"


def test_staging_pre_commit_detects_conflict_against_real_master(client, db_session):
    _seed_master(db_session, "TESTMAKE", "PRECHECK_MODEL", 2020, "MASTER001", 55, "MF")
    run_id = str(uuid.uuid4())
    _stage_row(db_session, run_id, "TESTMAKE", "PRECHECK_MODEL", 2020, "STAGED001", 70, "AGM", conflict=False)

    resp = client.get("/api/admin/pipeline/web-validate/staging/pre-commit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conflict_count"] == 1
    assert body["conflicts"][0]["make_n"] == "TESTMAKE"

    row = db_session.execute(text(
        "SELECT conflict FROM web_battery_staging WHERE make_n='TESTMAKE' AND model_n='PRECHECK_MODEL'"
    )).fetchone()
    assert row.conflict is True


# ---------------------------------------------------------------------------
# _upsert_rows / _try_reserve_quota — raw engine, called from a background
# thread in production, not request-scoped; can't join db_session's
# transaction, so these seed/clean up directly with a distinctive marker.
# ---------------------------------------------------------------------------

@pytest.fixture()
def _cleanup_verifytest_rows():
    def _cleanup():
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM web_battery_staging WHERE make_n = 'VERIFYTESTMAKE'"))
            conn.execute(text("DELETE FROM web_battery_validation WHERE make_n = 'VERIFYTESTMAKE'"))
            conn.execute(text("DELETE FROM api_usage_quota WHERE provider = 'verifytest-provider'"))
    _cleanup()
    yield
    _cleanup()


def test_upsert_rows_writes_to_staging_not_master(_cleanup_verifytest_rows):
    run_id = str(uuid.uuid4())
    rows = [{
        "make_n": "VERIFYTESTMAKE", "model_n": "MODEL1", "year": 2021,
        "battery_code": "BC001", "ah": 50, "technology": "MF",
        "source": "test", "engine_cc": 1500, "fuel_type": "PETROL",
    }]
    _upsert_rows(engine, rows, run_id=run_id, truncate_staging_first=True)

    with engine.connect() as conn:
        master_count = conn.execute(text(
            "SELECT COUNT(*) FROM web_battery_validation WHERE make_n='VERIFYTESTMAKE'"
        )).scalar()
        staging_row = conn.execute(text(
            "SELECT battery_code, is_valid FROM web_battery_staging WHERE make_n='VERIFYTESTMAKE'"
        )).fetchone()

    assert master_count == 0, "scrape results must never land in master before commit"
    assert staging_row is not None
    assert staging_row.battery_code == "BC001"
    assert staging_row.is_valid is True


def test_try_reserve_quota_enforces_limit_under_concurrency(_cleanup_verifytest_rows):
    provider = "verifytest-provider"
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO api_usage_quota (provider, month, calls_made, quota_limit, updated_at, period_start, period_end)
            VALUES (:p, :m, 0, :ql, :now, :now, :end)
        """), {"p": provider, "m": now.strftime("%Y-%m"), "ql": 20, "now": now, "end": now + timedelta(days=30)})

    allowed = []

    def worker(_):
        allowed.append(_try_reserve_quota(engine, provider))

    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(worker, range(100)))

    assert sum(allowed) == 20, "exactly quota_limit calls should be allowed, even under concurrency"

    with engine.connect() as conn:
        db_calls_made = conn.execute(
            text("SELECT calls_made FROM api_usage_quota WHERE provider=:p"), {"p": provider}
        ).scalar()
    assert db_calls_made == 20
