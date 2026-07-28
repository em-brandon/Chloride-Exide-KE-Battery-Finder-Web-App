"""
On-demand Postgres backup, triggered from the admin panel.

Mirrors db-backup-script/backup-db.ps1 exactly (same container name, db
user/name defaults, `pg_dump -F c` custom format, same backups/ directory
and retention policy) so admin-panel backups and the manual PowerShell
script are interchangeable — a dump made by one can be restored with the
other's counterpart script.

Local-Docker-only today: this shells out to `docker exec`/`docker cp`
against the named local container. There is no RDS-compatible path yet —
production would need a direct pg_dump/psql connection or an RDS snapshot
API call instead (see CLAUDE.md's web-validation-region-bug entry for the
tracked follow-up). All subprocess arguments are fixed constants, never
built from request input, so this is safe to run with a real shell-less
subprocess call despite shelling out to `docker`.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = _REPO_ROOT / "backups"

CONTAINER_NAME = "battery-finder-postgres"
DB_USER = "batteryfinder"
DB_NAME = "batteryfinderdev"
DEFAULT_KEEP_COUNT = 10

# Backup filenames are always generated server-side as f"{DB_NAME}_{timestamp}.dump"
# — this pattern is also used to validate that a requested download filename
# can't escape BACKUP_DIR (path-traversal guard, same shape as the SPA
# fallback fix).
_FILENAME_PREFIX = f"{DB_NAME}_"
_FILENAME_SUFFIX = ".dump"


class BackupError(Exception):
    """Raised when a backup step (docker exec/cp) fails."""


@dataclass
class BackupResult:
    filename: str
    size_bytes: int
    created_at: datetime


@dataclass
class BackupInfo:
    filename: str
    size_bytes: int
    modified_at: datetime


def _container_running() -> bool:
    proc = subprocess.run(
        ["docker", "ps", "--filter", f"name={CONTAINER_NAME}", "--filter", "status=running",
         "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    return proc.returncode == 0 and CONTAINER_NAME in proc.stdout.split()


def _run(args: list[str], step: str) -> None:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=120, check=False)
    if proc.returncode != 0:
        raise BackupError(f"{step} failed: {proc.stderr.strip() or proc.stdout.strip()}")


def create_backup(keep_count: int = DEFAULT_KEEP_COUNT) -> BackupResult:
    """
    Dump the local Docker Postgres database, copy it out of the container
    into BACKUP_DIR, and prune old dumps beyond keep_count. Raises
    BackupError on any failure (container not running, pg_dump failing,
    empty dump file, etc.) — callers should catch this and record it.
    """
    if not _container_running():
        raise BackupError(
            f"Container '{CONTAINER_NAME}' is not running. Start it with: docker compose up -d"
        )

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dump_filename = f"{_FILENAME_PREFIX}{timestamp}{_FILENAME_SUFFIX}"
    remote_path = f"/tmp/{dump_filename}"

    _run(
        ["docker", "exec", CONTAINER_NAME, "pg_dump", "-U", DB_USER, "-d", DB_NAME,
         "-F", "c", "-f", remote_path],
        "pg_dump",
    )
    _run(["docker", "exec", CONTAINER_NAME, "test", "-s", remote_path], "dump size check")

    local_path = BACKUP_DIR / dump_filename
    _run(["docker", "cp", f"{CONTAINER_NAME}:{remote_path}", str(local_path)], "docker cp")
    _run(["docker", "exec", CONTAINER_NAME, "rm", remote_path], "remote cleanup")

    if not local_path.exists() or local_path.stat().st_size == 0:
        raise BackupError("Copied dump file is missing or empty")

    _prune_old_backups(keep_count)

    return BackupResult(
        filename=dump_filename,
        size_bytes=local_path.stat().st_size,
        created_at=datetime.now(timezone.utc),
    )


def _prune_old_backups(keep_count: int) -> None:
    dumps = sorted(
        BACKUP_DIR.glob(f"{_FILENAME_PREFIX}*{_FILENAME_SUFFIX}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in dumps[keep_count:]:
        old.unlink(missing_ok=True)


def list_backups() -> list[BackupInfo]:
    if not BACKUP_DIR.exists():
        return []
    dumps = sorted(
        BACKUP_DIR.glob(f"{_FILENAME_PREFIX}*{_FILENAME_SUFFIX}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [
        BackupInfo(
            filename=p.name,
            size_bytes=p.stat().st_size,
            modified_at=datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc),
        )
        for p in dumps
    ]


def resolve_backup_path(filename: str) -> Path:
    """
    Validate a requested filename and resolve it to a path guaranteed to
    stay inside BACKUP_DIR. Raises ValueError for anything that doesn't
    match the exact server-generated pattern (rejects path separators,
    '..', or any name not matching `{DB_NAME}_<timestamp>.dump`) — same
    normalize-and-contain treatment as the SPA fallback path-traversal fix.
    """
    if not filename.startswith(_FILENAME_PREFIX) or not filename.endswith(_FILENAME_SUFFIX):
        raise ValueError("Invalid backup filename")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError("Invalid backup filename")

    candidate = os.path.normpath(os.path.join(str(BACKUP_DIR), filename))
    backup_root = os.path.normpath(str(BACKUP_DIR)) + os.sep
    if not candidate.startswith(backup_root):
        raise ValueError("Invalid backup filename")
    if not os.path.isfile(candidate):
        raise ValueError("Backup file not found")
    return Path(candidate)
