"""
Integration tests for the CRSP staging pipeline's commit/discard/revert
lifecycle against the real local Postgres. Exercises the DB state machine
directly (staging rows inserted via the ORM) rather than running the actual
enrich_years.py pipeline, which calls out to live external APIs.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import VehicleYear, VehicleYearChangelog, VehicleYearStaging, VehicleYearVersion


def _stage_row(db_session, make="TOYOTA", model="COROLLA", year=2015, run_id=None):
    row = VehicleYearStaging(
        run_id=run_id or str(uuid.uuid4()),
        make=make, model=model, year=year,
        engine_capacity=1500, fuel="PETROL", source="fueleconomy",
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_get_staging_conflicts_and_new_filters(client, db_session):
    # Regression test: VehicleYearStaging.conflict/is_valid are real Postgres
    # `boolean` columns (per the migration), but models.py previously declared
    # them as Integer, so `.filter(VehicleYearStaging.conflict == 0)` rendered
    # an `boolean = integer` comparison that Postgres rejects outright — every
    # call to this endpoint with filter=conflicts or filter=new was a 500.
    conflicting = VehicleYearStaging(
        run_id=str(uuid.uuid4()), make="TOYOTA", model="HILUX", year=2018,
        engine_capacity=2800, fuel="DIESEL", source="fueleconomy",
        conflict=True, conflict_detail=None,
    )
    clean = VehicleYearStaging(
        run_id=str(uuid.uuid4()), make="TOYOTA", model="VITZ", year=2016,
        engine_capacity=1000, fuel="PETROL", source="fueleconomy",
    )
    db_session.add_all([conflicting, clean])
    db_session.commit()

    conflicts_resp = client.get("/api/admin/pipeline/crsp/staging", params={"filter": "conflicts"})
    assert conflicts_resp.status_code == 200
    conflicts_makes = {r["make"] for r in conflicts_resp.json()["rows"]}
    assert conflicts_makes == {"TOYOTA"}
    assert conflicts_resp.json()["total"] == 1

    new_resp = client.get("/api/admin/pipeline/crsp/staging", params={"filter": "new"})
    assert new_resp.status_code == 200
    assert new_resp.json()["total"] == 1
    assert new_resp.json()["rows"][0]["model"] == "VITZ"


def test_commit_staging_with_no_rows_returns_400(client):
    resp = client.post("/api/admin/pipeline/crsp/staging/commit", json={})
    assert resp.status_code == 400


def test_commit_staging_adds_new_rows_and_clears_staging(client, db_session):
    _stage_row(db_session, make="TOYOTA", model="COROLLA", year=2015)

    resp = client.post("/api/admin/pipeline/crsp/staging/commit", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["committed"] == 1
    assert body["skipped_existing"] == 0

    db_session.expire_all()
    assert db_session.query(VehicleYearStaging).count() == 0
    veh = db_session.query(VehicleYear).filter(
        VehicleYear.make == "TOYOTA", VehicleYear.model == "COROLLA", VehicleYear.year == 2015,
    ).first()
    assert veh is not None

    version = db_session.query(VehicleYearVersion).filter(
        VehicleYearVersion.id == body["version_id"]
    ).first()
    assert version is not None
    assert version.committed_count == 1

    changelog = db_session.query(VehicleYearChangelog).filter(
        VehicleYearChangelog.version_id == body["version_id"]
    ).all()
    assert len(changelog) == 1
    assert changelog[0].change_type == "added"


def test_commit_staging_skips_rows_that_already_exist(client, db_session):
    db_session.add(VehicleYear(make="TOYOTA", model="COROLLA", year=2015, engine_capacity=1500, fuel="PETROL"))
    db_session.commit()
    _stage_row(db_session, make="TOYOTA", model="COROLLA", year=2015)

    resp = client.post("/api/admin/pipeline/crsp/staging/commit", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["committed"] == 0
    assert body["skipped_existing"] == 1

    db_session.expire_all()
    assert db_session.query(VehicleYear).filter(
        VehicleYear.make == "TOYOTA", VehicleYear.model == "COROLLA", VehicleYear.year == 2015,
    ).count() == 1


def test_discard_staging_clears_rows_without_committing(client, db_session):
    _stage_row(db_session, make="HONDA", model="FIT", year=2016)

    resp = client.post("/api/admin/pipeline/crsp/staging/discard")
    assert resp.status_code == 200

    db_session.expire_all()
    assert db_session.query(VehicleYearStaging).count() == 0
    assert db_session.query(VehicleYear).filter(
        VehicleYear.make == "HONDA", VehicleYear.model == "FIT",
    ).count() == 0


def test_revert_version_not_found_returns_404(client):
    resp = client.post(f"/api/admin/pipeline/crsp/versions/{uuid.uuid4()}/revert")
    assert resp.status_code == 404


def test_revert_added_version_deletes_the_rows_it_added(client, db_session):
    # Regression test for the FK-violation bug fixed on main (76a13f9):
    # revert previously 500'd because the new VehicleYearVersion row wasn't
    # flushed before changelog rows referencing its id were added.
    _stage_row(db_session, make="MAZDA", model="CX 5", year=2019)
    commit_resp = client.post("/api/admin/pipeline/crsp/staging/commit", json={})
    assert commit_resp.status_code == 200
    version_id = commit_resp.json()["version_id"]

    revert_resp = client.post(f"/api/admin/pipeline/crsp/versions/{version_id}/revert")
    assert revert_resp.status_code == 200
    revert_body = revert_resp.json()
    assert revert_body["rows_reversed"] == 1

    db_session.expire_all()
    assert db_session.query(VehicleYear).filter(
        VehicleYear.make == "MAZDA", VehicleYear.model == "CX 5", VehicleYear.year == 2019,
    ).count() == 0

    new_version_id = revert_body["new_version_id"]
    new_changelog = db_session.query(VehicleYearChangelog).filter(
        VehicleYearChangelog.version_id == new_version_id
    ).all()
    assert len(new_changelog) == 1
    assert new_changelog[0].change_type == "removed"
