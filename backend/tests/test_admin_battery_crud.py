"""
Integration tests for the battery CRUD routes (create/update/delete) against
the real local Postgres — edge cases: duplicate codes, missing ids, and
soft-delete interaction with the battery_code uniqueness constraint.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import BatterySpec


def _battery_payload(code="TEST-CODE-1", model_key="TEST MODEL", ah=50, cca_en=400, technology="MF"):
    return {
        "battery_code": code,
        "model_key": model_key,
        "ah": ah,
        "cca_en": cca_en,
        "technology": technology,
    }


def test_create_battery_success(client):
    resp = client.post("/api/admin/batteries", json=_battery_payload("NEWCODE1"))
    assert resp.status_code == 201
    assert resp.json()["battery_code"] == "NEWCODE1"


def test_create_battery_duplicate_code_returns_409(client, db_session):
    db_session.add(BatterySpec(battery_code="DUPCODE", model_key="M", ah=50, cca_en=400, technology="MF"))
    db_session.commit()

    resp = client.post("/api/admin/batteries", json=_battery_payload("DUPCODE"))
    assert resp.status_code == 409


def test_update_battery_not_found_returns_404(client):
    resp = client.patch("/api/admin/batteries/999999", json=_battery_payload())
    assert resp.status_code == 404


def test_update_battery_duplicate_code_conflicts_returns_409(client, db_session):
    a = BatterySpec(battery_code="CODE-A", model_key="M", ah=50, cca_en=400, technology="MF")
    b = BatterySpec(battery_code="CODE-B", model_key="M", ah=50, cca_en=400, technology="MF")
    db_session.add_all([a, b])
    db_session.commit()

    resp = client.patch(f"/api/admin/batteries/{b.id}", json=_battery_payload("CODE-A"))
    assert resp.status_code == 409


def test_update_battery_allows_keeping_same_code(client, db_session):
    a = BatterySpec(battery_code="CODE-C", model_key="OLD MODEL", ah=50, cca_en=400, technology="MF")
    db_session.add(a)
    db_session.commit()

    resp = client.patch(f"/api/admin/batteries/{a.id}", json=_battery_payload("CODE-C", model_key="NEW MODEL"))
    assert resp.status_code == 200


def test_delete_battery_not_found_returns_404(client):
    resp = client.delete("/api/admin/batteries/999999")
    assert resp.status_code == 404


def test_delete_battery_soft_deletes_and_excludes_from_list(client, db_session):
    a = BatterySpec(battery_code="TO-DELETE", model_key="M", ah=50, cca_en=400, technology="MF")
    db_session.add(a)
    db_session.commit()
    battery_id = a.id

    resp = client.delete(f"/api/admin/batteries/{battery_id}")
    assert resp.status_code == 200

    db_session.expire_all()
    row = db_session.query(BatterySpec).filter(BatterySpec.id == battery_id).first()
    assert row is not None
    assert row.deleted_at is not None

    listing = client.get("/api/admin/batteries", params={"search": "TO-DELETE"})
    assert all(item["battery_code"] != "TO-DELETE" for item in listing.json()["items"])


def test_create_battery_reusing_code_of_a_soft_deleted_row_returns_409(client, db_session):
    # battery_code has a DB-level UNIQUE constraint regardless of deleted_at,
    # so re-creating a code that belongs to a soft-deleted row must be
    # rejected with a clean 409 rather than a 500 IntegrityError from the
    # UNIQUE constraint violation.
    old = BatterySpec(
        battery_code="REUSED-CODE", model_key="OLD", ah=50, cca_en=400,
        technology="MF", deleted_at=datetime.now(timezone.utc),
    )
    db_session.add(old)
    db_session.commit()

    resp = client.post("/api/admin/batteries", json=_battery_payload("REUSED-CODE"))
    assert resp.status_code == 409
