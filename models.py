"""
SQLAlchemy ORM models.

Tables
------
vehicles_raw      — cleaned CSRP dealer records (output of dataprep.py)
vehicle_years     — per-model year ranges with cc/fuel (output of enrich_years.py)
                    READ at runtime by matcher.py
battery_specs     — battery catalogue (seeded from battery_specs_output.xlsx)
                    READ at runtime by matcher.py
model_aliases     — international → JDM model name mappings (seeded from model_aliases.csv)
                    READ at runtime by matcher.py

Admin tables (written by admin dashboard)
-----------------------------------------
admin_users       — hashed credentials for dashboard login
admin_sessions    — HTTP-only cookie session store (8-hour expiry)
battery_audit_log — full change history for battery_specs (INSERT/UPDATE/DELETE)
admin_stats       — persisted counters (e.g. total DB reads)
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Float,
    Text,
    UniqueConstraint,
)

from db import Base


class VehicleRaw(Base):
    """
    Intermediate staging table — one row per unique make/model/engine_capacity/fuel
    combination from the raw CSRP Excel file.

    Written by: dataprep.py
    Read by:    enrich_years.py (as input for year-range enrichment)
    """

    __tablename__ = "vehicles_raw"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    make             = Column(String(100), nullable=False)
    model            = Column(String(200), nullable=False)
    model_number     = Column(String(100), nullable=True)
    engine_capacity  = Column(Integer,     nullable=True)
    fuel             = Column(String(50),  nullable=True)

    __table_args__ = (
        UniqueConstraint("make", "model", "engine_capacity", "fuel", name="uq_vehicles_raw"),
        Index("ix_vehicles_raw_make_model", "make", "model"),
    )

    def __repr__(self) -> str:
        return f"<VehicleRaw {self.make} {self.model} {self.engine_capacity}cc {self.fuel}>"


class VehicleYear(Base):
    """
    Primary runtime lookup table — one row per make/model/year combination,
    including the typical engine capacity and fuel type for that trim year.

    Written by: admin_router.py (commit from vehicle_years_staging after admin review)
    Read by:    matcher.py (loaded once into a DataFrame at startup)
    """

    __tablename__ = "vehicle_years"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    make             = Column(String(100), nullable=False)
    model            = Column(String(200), nullable=False)
    year             = Column(Integer,     nullable=False)
    engine_capacity  = Column(Integer,     nullable=True)
    fuel             = Column(String(50),  nullable=True)
    source           = Column(String(50),  nullable=True)  # fueleconomy|carapi|wikipedia|wikidata|nhtsa

    __table_args__ = (
        UniqueConstraint("make", "model", "year", name="uq_vehicle_years"),
        Index("ix_vehicle_years_make",       "make"),
        Index("ix_vehicle_years_make_model", "make", "model"),
    )

    def __repr__(self) -> str:
        return f"<VehicleYear {self.make} {self.model} {self.year}>"


class BatterySpec(Base):
    """
    Battery catalogue — one row per battery SKU.

    Column naming mirrors the original Excel file to keep seed.py simple.
    matcher.py renames columns when loading into a DataFrame.

    Written by: seed.py (initial load from battery_specs_output.xlsx)
                remove_ultrapower.py (deletes rows containing 'ULTRAPOWER')
    Read by:    matcher.py (loaded once at startup)
    """

    __tablename__ = "battery_specs"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    battery_code = Column(String(100), nullable=False, unique=True)
    model_key    = Column(String(100), nullable=False)
    ah           = Column(Float,       nullable=True)
    cca_en       = Column(Float,       nullable=True)
    technology   = Column(String(100), nullable=True)
    origin       = Column(String(50),  nullable=True)   # 'local' | 'imported'
    brand        = Column(String(100), nullable=True)   # e.g. Powerlast, Sebang
    deleted_at   = Column(DateTime(timezone=True), nullable=True)   # soft delete

    __table_args__ = (
        Index("ix_battery_specs_model_key", "model_key"),
        Index("ix_battery_specs_ah",        "ah"),
    )

    def __repr__(self) -> str:
        return f"<BatterySpec {self.battery_code} {self.ah}Ah {self.technology}>"


class ModelAlias(Base):
    """
    International model name → JDM model name mapping.

    Used to resolve user inputs like 'COROLLA' to the JDM trim names
    stored in vehicle_years (e.g. AXIO, FIELDER, ALLION).

    Written by: seed.py (initial load from model_aliases.csv)
    Read by:    matcher.py (loaded once at startup)
    """

    __tablename__ = "model_aliases"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    make                = Column(String(100), nullable=False)
    international_model = Column(String(200), nullable=False)
    jdm_model           = Column(String(200), nullable=False)
    priority            = Column(Integer,     nullable=False, default=999)

    __table_args__ = (
        UniqueConstraint(
            "make", "international_model", "jdm_model",
            name="uq_model_aliases",
        ),
        Index("ix_model_aliases_make_intl", "make", "international_model"),
    )

    def __repr__(self) -> str:
        return f"<ModelAlias {self.make} {self.international_model} → {self.jdm_model}>"


# ---------------------------------------------------------------------------
# Admin tables
# ---------------------------------------------------------------------------

class AdminUser(Base):
    """
    Admin dashboard user account.

    Passwords are stored as bcrypt hashes — never plaintext.
    Written by: create_admin.py (CLI) or future admin management endpoints.
    Read by:    admin_auth.py (login verification).
    """

    __tablename__ = "admin_users"

    id            = Column(Integer,              primary_key=True, autoincrement=True)
    username      = Column(String(100),          nullable=False, unique=True)
    password_hash = Column(String(255),          nullable=False)
    created_at    = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_admin_users_username", "username", unique=True),
    )

    def __repr__(self) -> str:
        return f"<AdminUser {self.username}>"


class AdminSession(Base):
    """
    HTTP-only cookie session.

    One row per active login. Expires after 8 hours.
    Deleted on logout or manual revocation from the sessions panel.
    Written/read by: admin_auth.py.
    """

    __tablename__ = "admin_sessions"

    id            = Column(Integer,              primary_key=True, autoincrement=True)
    session_token = Column(String(64),           nullable=False, unique=True)
    admin_id      = Column(Integer,              ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False)
    created_at    = Column(DateTime(timezone=True), nullable=False)
    expires_at    = Column(DateTime(timezone=True), nullable=False)
    ip_address    = Column(String(45),           nullable=True)

    __table_args__ = (
        Index("ix_admin_sessions_token",    "session_token", unique=True),
        Index("ix_admin_sessions_admin_id", "admin_id"),
    )

    def __repr__(self) -> str:
        return f"<AdminSession admin_id={self.admin_id} expires={self.expires_at}>"


class BatteryAuditLog(Base):
    """
    Immutable change history for battery_specs.

    One row per INSERT, UPDATE, or DELETE action.
    old_values and new_values are JSON strings of the battery row at that point.
    Written by: admin_router.py (all battery mutating endpoints).
    Read by:    /api/admin/audit endpoint.
    """

    __tablename__ = "battery_audit_log"

    id          = Column(Integer,              primary_key=True, autoincrement=True)
    battery_id  = Column(Integer,             ForeignKey("battery_specs.id", ondelete="SET NULL"), nullable=True)
    action      = Column(String(10),          nullable=False)   # INSERT | UPDATE | DELETE
    changed_by  = Column(String(100),         nullable=False)   # admin username
    changed_at  = Column(DateTime(timezone=True), nullable=False)
    old_values  = Column(Text,                nullable=True)    # JSON
    new_values  = Column(Text,                nullable=True)    # JSON

    __table_args__ = (
        Index("ix_battery_audit_battery_id", "battery_id"),
        Index("ix_battery_audit_changed_at", "changed_at"),
    )

    def __repr__(self) -> str:
        return f"<BatteryAuditLog {self.action} battery_id={self.battery_id} by={self.changed_by}>"


class AdminStats(Base):
    """
    Persisted counters that survive server restarts.

    Keys:
      'db_reads' — cumulative count of GET /api/* requests served.

    Written by: read-counter middleware in app.py (batched every 60 s).
    Read by:    /api/admin/stats endpoint.
    """

    __tablename__ = "admin_stats"

    id          = Column(Integer,              primary_key=True, autoincrement=True)
    stat_key    = Column(String(100),          nullable=False, unique=True)
    stat_value  = Column(BigInteger,           nullable=False, default=0)
    updated_at  = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_admin_stats_key", "stat_key", unique=True),
    )

    def __repr__(self) -> str:
        return f"<AdminStats {self.stat_key}={self.stat_value}>"


class SearchEvent(Base):
    """
    One row per /api/recommend call. Written fire-and-forget in a background
    thread by app.py so it never adds latency to the recommendation response.

    match_type values (from matcher.py):
      'Exact Match', 'Web-Validated Match', 'Real-World Data Match' → matched=True
      'Close Match'                                                  → matched=True
      'Estimated (Rule-Based)'                                       → matched=False
    """

    __tablename__ = "search_events"

    id               = Column(Integer,               primary_key=True, autoincrement=True)
    timestamp        = Column(DateTime(timezone=True), nullable=False)
    make             = Column(String(80),            nullable=True)
    model            = Column(String(80),            nullable=True)
    year             = Column(Integer,               nullable=True)
    engine_cc        = Column(Integer,               nullable=True)
    fuel_type        = Column(String(20),            nullable=True)
    battery_returned = Column(String(50),            nullable=True)
    battery_ah       = Column(Integer,               nullable=True)
    match_type       = Column(String(50),            nullable=True)
    confidence       = Column(Integer,               nullable=True)
    matched          = Column(Boolean,               nullable=False, default=False)
    ip_address       = Column(String(45),            nullable=True)

    __table_args__ = (
        Index("ix_search_events_timestamp", "timestamp"),
    )


class AppSettings(Base):
    """
    Generic key-value store for runtime-toggleable app settings.

    Keys:
      'maintenance_mode' — 'true' / 'false'; served by spa_fallback in app.py.
    """

    __tablename__ = "app_settings"

    id            = Column(Integer,                  primary_key=True, autoincrement=True)
    setting_key   = Column(String(100),              nullable=False, unique=True)
    setting_value = Column(String(500),              nullable=False, default='')
    updated_at    = Column(DateTime(timezone=True),  nullable=False)
    updated_by    = Column(String(100),              nullable=True)

    __table_args__ = (Index("ix_app_settings_key", "setting_key", unique=True),)

    def __repr__(self) -> str:
        return f"<AppSettings {self.setting_key}={self.setting_value}>"


class ApiUsageQuota(Base):
    """
    30-day rolling API call counter for the web_battery_validate pipeline providers.

    One row per (provider, month). quota_limit=-1 means unlimited.
    period_start/period_end define the 30-day window; after period_end a new row
    is created automatically by _ensure_quota_row().
    Written by: pipelines/web_battery_validate.py (incremented per call).
    Read by:    GET /api/admin/pipeline/quotas (admin dashboard).
    """

    __tablename__ = "api_usage_quota"

    id           = Column(Integer,               primary_key=True, autoincrement=True)
    provider     = Column(String(50),            nullable=False)
    month        = Column(String(7),             nullable=False)   # "YYYY-MM" of period_start
    calls_made   = Column(Integer,               nullable=False, default=0)
    quota_limit  = Column(Integer,               nullable=False, default=-1)  # -1 = unlimited
    updated_at   = Column(DateTime(timezone=True), nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=True)
    period_end   = Column(DateTime(timezone=True), nullable=True)  # period_start + 30 days

    __table_args__ = (
        UniqueConstraint("provider", "month", name="uq_api_usage_quota_provider_month"),
        Index("ix_api_usage_quota_provider_month", "provider", "month"),
    )

    def __repr__(self) -> str:
        return f"<ApiUsageQuota {self.provider} {self.month} {self.calls_made}/{self.quota_limit}>"


class UserFeedback(Base):
    """
    Stores user feedback submitted via the FeedbackModal after a battery recommendation.

    One row per submission.
    Written by: POST /api/feedback (public endpoint in app.py).
    Read by:    GET /api/admin/feedback (admin endpoint in admin_router.py).
    """

    __tablename__ = "user_feedback"

    id               = Column(Integer,              primary_key=True, autoincrement=True)
    vehicle_label    = Column(String(300),          nullable=False)          # e.g. "Toyota Camry 2020"
    satisfaction     = Column(Integer,              nullable=False)          # 1-5 stars
    accuracy         = Column(String(20),           nullable=True)           # exact|close|wrong|unsure
    wrong_parts      = Column(Text,                 nullable=True)           # JSON object
    comments         = Column(Text,                 nullable=True)
    submitted_at     = Column(DateTime(timezone=True), nullable=False)
    ip_address       = Column(String(45),           nullable=True)
    test_user_id     = Column(Integer,              ForeignKey("test_users.id", ondelete="SET NULL"), nullable=True)
    input_type       = Column(String(20),           nullable=True)           # select|type
    match_confidence = Column(Integer,              nullable=True)           # 0-100 from recommendation
    match_type       = Column(String(50),           nullable=True)           # exact_match|close_match|fallback etc.
    recommended_battery = Column(String(100),       nullable=True)           # primary battery code returned

    __table_args__ = (
        Index("ix_user_feedback_submitted_at", "submitted_at"),
        Index("ix_user_feedback_accuracy",     "accuracy"),
    )

    def __repr__(self) -> str:
        return f"<UserFeedback vehicle={self.vehicle_label!r} satisfaction={self.satisfaction}>"


# ---------------------------------------------------------------------------
# Test-user tables (for controlled tester sessions)
# ---------------------------------------------------------------------------

class TestUser(Base):
    """
    A registered test user who can log in via /login on the public finder.

    Passwords stored as bcrypt hashes.
    Written by: POST /api/auth/register.
    Read by:    POST /api/auth/login, GET /api/auth/me.
    """

    __tablename__ = "test_users"

    id            = Column(Integer,              primary_key=True, autoincrement=True)
    username      = Column(String(100),          nullable=False, unique=True)
    email         = Column(String(255),          nullable=True,  unique=True)
    password_hash = Column(String(255),          nullable=False)
    created_at    = Column(DateTime(timezone=True), nullable=False)
    is_active     = Column(Integer,              nullable=False, default=1)  # 1=active, 0=suspended

    __table_args__ = (
        Index("ix_test_users_username", "username", unique=True),
    )

    def __repr__(self) -> str:
        return f"<TestUser {self.username}>"


class TestUserSession(Base):
    """
    Bearer-token session for test users.

    Token is stored in the client's localStorage.
    Expires after 24 hours. Revocable by admin.
    Written/read by: app.py auth endpoints.
    Read by:         admin_router.py /api/admin/test-sessions.
    """

    __tablename__ = "test_user_sessions"

    id            = Column(Integer,              primary_key=True, autoincrement=True)
    session_token = Column(String(64),           nullable=False, unique=True)
    user_id       = Column(Integer,              ForeignKey("test_users.id", ondelete="CASCADE"), nullable=False)
    created_at    = Column(DateTime(timezone=True), nullable=False)
    expires_at    = Column(DateTime(timezone=True), nullable=False)
    ip_address    = Column(String(45),           nullable=True)
    user_agent    = Column(String(300),          nullable=True)
    last_seen_at  = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_test_user_sessions_token",   "session_token", unique=True),
        Index("ix_test_user_sessions_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<TestUserSession user_id={self.user_id} expires={self.expires_at}>"


# ---------------------------------------------------------------------------
# CRSP pipeline staging + versioning
# ---------------------------------------------------------------------------

class VehicleYearStaging(Base):
    """
    Temporary hold for enriched rows from enrich_years.py pending admin review.

    Written by: pipelines/enrich_years.py (via admin_router.py background thread)
    Read/committed by: admin_router.py CRSP staging endpoints
    """

    __tablename__ = "vehicle_years_staging"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    run_id           = Column(Text,        nullable=False)
    make             = Column(String(100), nullable=False)
    model            = Column(String(200), nullable=False)
    year             = Column(Integer,     nullable=False)
    engine_capacity  = Column(Integer,     nullable=True)
    fuel             = Column(String(50),  nullable=True)
    source           = Column(String(50),  nullable=True)  # fueleconomy|carapi|wikipedia|wikidata|nhtsa
    staged_at        = Column(DateTime(timezone=True), nullable=True)
    is_valid         = Column(Integer,     nullable=False, default=1)   # 1=valid, 0=invalid
    invalid_reason   = Column(Text,        nullable=True)
    conflict         = Column(Integer,     nullable=False, default=0)   # 1=conflict with existing row
    conflict_detail  = Column(Text,        nullable=True)               # JSON {current:{...}, staged:{...}}

    __table_args__ = (
        UniqueConstraint("make", "model", "year", name="uq_vehicle_years_staging_key"),
        Index("ix_vehicle_years_staging_run_id",  "run_id"),
        Index("ix_vehicle_years_staging_conflict", "conflict"),
    )

    def __repr__(self) -> str:
        return f"<VehicleYearStaging {self.make} {self.model} {self.year} run={self.run_id[:8]}>"


class VehicleYearUnmatched(Base):
    """
    Make+model pairs that got no year match from any enrichment source.

    Written by: pipelines/enrich_years.py after each run.
    Read by: admin_router.py unmatched endpoints (GET + rerun).
    Persisted to DB so retry works after server restarts.
    """

    __tablename__ = "vehicle_years_unmatched"

    id          = Column(Integer,              primary_key=True, autoincrement=True)
    run_id      = Column(Text,                 nullable=False)
    make        = Column(String(100),          nullable=False)
    model       = Column(String(200),          nullable=False)
    fuel        = Column(String(50),           nullable=True)
    recorded_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_vehicle_years_unmatched_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<VehicleYearUnmatched {self.make} {self.model} run={self.run_id[:8]}>"


class VehicleYearVersion(Base):
    """
    One record per admin-approved merge of staged rows into vehicle_years.

    Enables version history and rollback.
    Written by: admin_router.py CRSP staging/commit endpoint.
    """

    __tablename__ = "vehicle_years_versions"

    id               = Column(Text,    primary_key=True)   # UUID
    version_number   = Column(Integer, nullable=False)
    committed_at     = Column(DateTime(timezone=True), nullable=True)
    run_id           = Column(Text,    nullable=True)
    committed_count  = Column(Integer, nullable=False, default=0)  # rows added/updated
    updated_count    = Column(Integer, nullable=False, default=0)
    removed_count    = Column(Integer, nullable=False, default=0)
    conflict_count   = Column(Integer, nullable=False, default=0)
    committed_by     = Column(String(100), nullable=True)
    initiated_by     = Column(String(100), nullable=True)
    notes            = Column(Text,    nullable=True)

    __table_args__ = (
        Index("ix_vehicle_years_versions_committed_at", "committed_at"),
    )

    def __repr__(self) -> str:
        return f"<VehicleYearVersion v{self.version_number} by={self.committed_by}>"


class VehicleYearChangelog(Base):
    """
    Row-level diff for each VehicleYearVersion commit.

    Stores old/new values as JSON so individual rows can be reverted.
    Written by: admin_router.py (on commit and revert).
    """

    __tablename__ = "vehicle_years_changelog"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    version_id   = Column(Text,    ForeignKey("vehicle_years_versions.id"), nullable=False)
    make         = Column(String(100), nullable=False)
    model        = Column(String(200), nullable=False)
    year         = Column(Integer,     nullable=False)
    change_type  = Column(Text,        nullable=False)   # 'added' | 'updated' | 'removed'
    old_values   = Column(Text,        nullable=True)    # JSON {engine_capacity, fuel, source}
    new_values   = Column(Text,        nullable=True)    # JSON {engine_capacity, fuel, source}

    __table_args__ = (
        Index("ix_vehicle_years_changelog_version_id", "version_id"),
    )

    def __repr__(self) -> str:
        return f"<VehicleYearChangelog {self.change_type} {self.make} {self.model} {self.year}>"


class EnrichmentCacheMeta(Base):
    """
    Tracks last-downloaded timestamps for external enrichment datasets.

    Keys:
      'fueleconomy_csv' — fueleconomy.gov EPA bulk CSV (cache/fueleconomy_vehicles.csv)
      'year_cache'      — NHTSA VPIC + CarAPI model lists (cache/year_cache.json)

    Written by: pipelines/enrich_years.py (after each download).
    Read by:    GET /api/admin/pipeline/crsp/cache-status.
    """

    __tablename__ = "enrichment_cache_meta"

    key             = Column(Text,       primary_key=True)   # 'fueleconomy_csv' | 'year_cache'
    downloaded_at   = Column(DateTime(timezone=True), nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    record_count    = Column(Integer,    nullable=True)
    notes           = Column(Text,       nullable=True)
    updated_at      = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<EnrichmentCacheMeta {self.key} downloaded={self.downloaded_at}>"


class FueleconomyVehicle(Base):
    """
    Row-level store for the fueleconomy.gov bulk EPA vehicles CSV (~47 k rows).

    Downloaded via admin UI (POST /pipeline/crsp/fueleconomy/download).
    Loaded into an in-process module-level cache by pipelines/enrich_years.py.
    Recommended refresh: every 180 days (EPA publishes new model-year data annually in Oct/Nov).
    """

    __tablename__ = "fueleconomy_vehicles"

    id    = Column(Integer,     primary_key=True, autoincrement=True)
    year  = Column(Integer,     nullable=False)
    make  = Column(String(100), nullable=False)
    model = Column(String(200), nullable=False)

    __table_args__ = (
        Index("ix_fueleconomy_vehicles_make_model", "make", "model"),
    )

    def __repr__(self) -> str:
        return f"<FueleconomyVehicle {self.year} {self.make} {self.model}>"
