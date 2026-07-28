"""
Tests for the on-demand database backup routes (admin_router.py's
/api/admin/backup* endpoints, backed by db_backup.py).

create_backup/list_backups shell out to `docker`, so these tests
monkeypatch admin_router.db_backup's functions rather than requiring a
running Docker container — the routes' own logic (audit logging on
success/failure, filename validation, download streaming) is what's under
test here, not db_backup.py's subprocess plumbing.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import admin_router
import db_backup
from models import AdminBackupLog


def test_create_backup_success_logs_and_returns_metadata(client, db_session, monkeypatch):
    result = db_backup.BackupResult(
        filename="batteryfinderdev_20260728_120000.dump",
        size_bytes=1234,
        created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(admin_router.db_backup, "create_backup", lambda **kw: result)

    resp = client.post("/api/admin/backup")
    assert resp.status_code == 201
    body = resp.json()
    assert body["filename"] == result.filename
    assert body["size_bytes"] == 1234

    log_row = db_session.query(AdminBackupLog).filter_by(filename=result.filename).one()
    assert log_row.status == "success"
    assert log_row.triggered_by == "test-admin"
    assert log_row.error_detail is None


def test_create_backup_failure_logs_and_returns_500(client, db_session, monkeypatch):
    def _boom(**kw):
        raise db_backup.BackupError("container not running")

    monkeypatch.setattr(admin_router.db_backup, "create_backup", _boom)

    resp = client.post("/api/admin/backup")
    assert resp.status_code == 500

    log_row = db_session.query(AdminBackupLog).filter_by(filename="").one()
    assert log_row.status == "failed"
    assert "container not running" in log_row.error_detail
    assert log_row.triggered_by == "test-admin"


def test_list_backups_returns_entries(client, monkeypatch):
    entries = [
        db_backup.BackupInfo(filename="batteryfinderdev_20260728_120000.dump", size_bytes=1234,
                              modified_at=datetime.now(timezone.utc)),
    ]
    monkeypatch.setattr(admin_router.db_backup, "list_backups", lambda: entries)

    resp = client.get("/api/admin/backup")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["backups"]) == 1
    assert body["backups"][0]["filename"] == entries[0].filename


def test_backup_log_endpoint_orders_newest_first(client, db_session):
    older = AdminBackupLog(
        filename="a.dump", size_bytes=1, status="success", error_detail=None,
        triggered_by="test-admin", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    newer = AdminBackupLog(
        filename="b.dump", size_bytes=2, status="success", error_detail=None,
        triggered_by="test-admin", created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    db_session.add_all([older, newer])
    db_session.flush()

    resp = client.get("/api/admin/backup/log")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items[0]["filename"] == "b.dump"
    assert items[1]["filename"] == "a.dump"


def test_download_rejects_path_traversal(client, monkeypatch):
    def _reject(filename):
        raise ValueError("Invalid backup filename")
    monkeypatch.setattr(admin_router.db_backup, "resolve_backup_path", _reject)

    resp = client.get("/api/admin/backup/..%2f..%2f.env/download")
    assert resp.status_code == 404


def test_download_streams_valid_file(client, monkeypatch, tmp_path):
    dump = tmp_path / "batteryfinderdev_20260728_120000.dump"
    dump.write_bytes(b"fake-dump-contents")
    monkeypatch.setattr(admin_router.db_backup, "resolve_backup_path", lambda filename: dump)

    resp = client.get("/api/admin/backup/batteryfinderdev_20260728_120000.dump/download")
    assert resp.status_code == 200
    assert resp.content == b"fake-dump-contents"
    assert "attachment" in resp.headers["content-disposition"]


def test_backup_routes_require_admin():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    test_app = FastAPI()
    test_app.include_router(admin_router.router)
    test_app.state.limiter = admin_router._limiter
    with TestClient(test_app) as anon_client:
        assert anon_client.post("/api/admin/backup").status_code in (401, 403)
        assert anon_client.get("/api/admin/backup").status_code in (401, 403)
        assert anon_client.get("/api/admin/backup/log").status_code in (401, 403)
