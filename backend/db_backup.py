"""
On-demand Postgres backup, triggered from the admin panel.

Two modes, selected by the `DB_BACKUP_MODE` environment variable:

* `docker` (default) — shells out to `docker exec`/`docker cp` against the
  named local container. Mirrors db-backup-script/backup-db.ps1 exactly
  (same container name, db user/name defaults, `pg_dump -F c` custom format,
  same backups/ directory and retention policy) so admin-panel backups and
  the manual PowerShell script stay interchangeable — a dump made by one can
  be restored with the other's counterpart script.
* `direct` — runs a local `pg_dump` straight against the server over TCP,
  with connection details taken from `DATABASE_URL`. This is the mode for any
  deployment where Postgres is not a local Docker container: a self-hosted VM
  running native Postgres, or RDS.

Connection identity (user, database name, and in `direct` mode the host and
port) is read from the environment rather than hardcoded. It previously
defaulted to the *dev* database name, which meant a deployment using any
other naming would have silently dumped the wrong database — or nothing.

Subprocess arguments are built from environment configuration and
server-generated timestamps, never from request input, and every call runs
shell-less (`shell=False`), so no argument is subject to shell interpretation.
The database password is passed via `PGPASSWORD` in the child environment
rather than on the command line, so it never appears in the process table.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

# db.py loads .env as well, but db_backup.py is also imported directly by
# standalone scripts where db.py may not have been imported first — don't make
# configuration depend on import order. override=False keeps real environment
# variables winning over .env, exactly as in db.py.
load_dotenv(override=False)

_REPO_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = _REPO_ROOT / "backups"

DEFAULT_KEEP_COUNT = 10

MODE = os.environ.get("DB_BACKUP_MODE", "docker").strip().lower()
if MODE not in ("docker", "direct"):
    raise RuntimeError(
        f"DB_BACKUP_MODE must be 'docker' or 'direct', got {MODE!r}."
    )

CONTAINER_NAME = os.environ.get("DB_BACKUP_CONTAINER", "battery-finder-postgres")


def _connection_defaults() -> tuple[str | None, int | None, str, str, str | None]:
    """Derive (host, port, user, database, password) for the backup target.

    In `direct` mode these come from DATABASE_URL — the same connection string
    the application itself uses, so a backup can never silently target a
    different database than the one being served. Explicit DB_BACKUP_USER /
    DB_BACKUP_NAME override it either way. In `docker` mode the host and port
    are irrelevant (the dump runs inside the container) and the historical
    defaults are preserved so existing setups are unaffected.
    """
    host = port = password = None
    user = "batteryfinder"
    name = "batteryfinderdev"

    if MODE == "direct":
        raw_url = os.environ.get("DATABASE_URL")
        if not raw_url:
            raise RuntimeError(
                "DB_BACKUP_MODE=direct requires DATABASE_URL to be set — the "
                "backup target is derived from it."
            )
        url = make_url(raw_url)
        host = url.host or "127.0.0.1"
        port = url.port or 5432
        password = url.password
        user = url.username or user
        name = url.database or name

    return (
        host,
        port,
        os.environ.get("DB_BACKUP_USER") or user,
        os.environ.get("DB_BACKUP_NAME") or name,
        password,
    )


DB_HOST, DB_PORT, DB_USER, DB_NAME, _DB_PASSWORD = _connection_defaults()

# Backup filenames are always generated server-side as f"{DB_NAME}_{timestamp}.dump"
# — this pattern is also used to validate that a requested download filename
# can't escape BACKUP_DIR (path-traversal guard, same shape as the SPA
# fallback fix). Note this is keyed on the *configured* database name, so
# changing DB_BACKUP_NAME hides dumps taken under the previous name from
# list_backups(); they remain on disk and are not deleted by pruning.
_FILENAME_PREFIX = f"{DB_NAME}_"
_FILENAME_SUFFIX = ".dump"


class BackupError(Exception):
    """Raised when a backup step (pg_dump, or docker exec/cp) fails."""


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


def _run(args: list[str], step: str, env: dict[str, str] | None = None) -> None:
    proc = subprocess.run(
        args, capture_output=True, text=True, timeout=120, check=False, env=env,
    )
    if proc.returncode != 0:
        raise BackupError(f"{step} failed: {proc.stderr.strip() or proc.stdout.strip()}")


def create_backup(keep_count: int = DEFAULT_KEEP_COUNT) -> BackupResult:
    """
    Dump the Postgres database into BACKUP_DIR and prune old dumps beyond
    keep_count. Raises BackupError on any failure (container not running,
    pg_dump missing or failing, empty dump file, etc.) — callers should catch
    this and record it.

    Dispatches on MODE; both paths produce an identical `pg_dump -F c` custom
    format file, so dumps are interchangeable between modes.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dump_filename = f"{_FILENAME_PREFIX}{timestamp}{_FILENAME_SUFFIX}"
    local_path = BACKUP_DIR / dump_filename

    if MODE == "direct":
        _dump_direct(local_path)
    else:
        _dump_via_docker(dump_filename, local_path)

    if not local_path.exists() or local_path.stat().st_size == 0:
        local_path.unlink(missing_ok=True)
        raise BackupError("Dump file is missing or empty")

    _prune_old_backups(keep_count)

    return BackupResult(
        filename=dump_filename,
        size_bytes=local_path.stat().st_size,
        created_at=datetime.now(timezone.utc),
    )


def _dump_direct(local_path: Path) -> None:
    """Run pg_dump locally against the server over TCP, writing straight to disk."""
    if shutil.which("pg_dump") is None:
        raise BackupError(
            "pg_dump not found on PATH. Install the PostgreSQL client tools "
            "(e.g. `apt install postgresql-client-15`) or set DB_BACKUP_MODE=docker."
        )

    # PGPASSWORD rather than a command-line argument: the process table is
    # world-readable, argv is not a safe place for a credential.
    env = os.environ.copy()
    if _DB_PASSWORD:
        env["PGPASSWORD"] = _DB_PASSWORD

    # pg_dump -f creates the output file before it has finished (or even
    # connected), so a failure leaves a 0-byte file behind. Remove it rather
    # than let list_backups() advertise a broken dump as a real one. The docker
    # path can't hit this — there, the local file only appears after a
    # successful `docker cp`.
    try:
        _run(
            ["pg_dump", "-h", str(DB_HOST), "-p", str(DB_PORT), "-U", DB_USER,
             "-d", DB_NAME, "-F", "c", "-f", str(local_path)],
            "pg_dump",
            env=env,
        )
    except BackupError:
        local_path.unlink(missing_ok=True)
        raise


def _dump_via_docker(dump_filename: str, local_path: Path) -> None:
    """Dump inside the local Docker container, then copy the file out."""
    if not _container_running():
        raise BackupError(
            f"Container '{CONTAINER_NAME}' is not running. Start it with: docker compose up -d"
        )

    remote_path = f"/tmp/{dump_filename}"

    _run(
        ["docker", "exec", CONTAINER_NAME, "pg_dump", "-U", DB_USER, "-d", DB_NAME,
         "-F", "c", "-f", remote_path],
        "pg_dump",
    )
    _run(["docker", "exec", CONTAINER_NAME, "test", "-s", remote_path], "dump size check")
    _run(["docker", "cp", f"{CONTAINER_NAME}:{remote_path}", str(local_path)], "docker cp")
    _run(["docker", "exec", CONTAINER_NAME, "rm", remote_path], "remote cleanup")


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
