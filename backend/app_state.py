import time

# Per-process cache with a 5-second TTL.
# Each worker refreshes from the DB independently, so all workers and all
# EC2 instances converge within 5 seconds of a toggle — no Redis needed.
_cache: dict = {"value": False, "expires": 0.0}
_TTL = 5.0


def is_maintenance_mode() -> bool:
    now = time.monotonic()
    if now >= _cache["expires"]:
        _refresh()
    return _cache["value"]


def set_maintenance_mode(enabled: bool) -> None:
    # Update the local cache immediately so this process sees the change
    # without waiting for the next TTL expiry.
    _cache["value"] = enabled
    _cache["expires"] = time.monotonic() + _TTL


def _refresh() -> None:
    try:
        from db import SessionLocal
        from models import AppSettings
        with SessionLocal() as db:
            row = db.query(AppSettings).filter_by(setting_key="maintenance_mode").first()
            _cache["value"] = (row.setting_value == "true") if row else False
    except Exception:
        pass  # keep stale value on DB error rather than crashing every request
    _cache["expires"] = time.monotonic() + _TTL
