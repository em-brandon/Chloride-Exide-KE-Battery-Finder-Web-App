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

    Written by: enrich_years.py (upserts by make+model+year)
    Read by:    matcher.py (loaded once into a DataFrame at startup)
    """

    __tablename__ = "vehicle_years"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    make             = Column(String(100), nullable=False)
    model            = Column(String(200), nullable=False)
    year             = Column(Integer,     nullable=False)
    engine_capacity  = Column(Integer,     nullable=True)
    fuel             = Column(String(50),  nullable=True)

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
