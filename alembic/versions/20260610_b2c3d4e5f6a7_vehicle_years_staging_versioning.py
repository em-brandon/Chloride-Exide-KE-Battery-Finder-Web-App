"""vehicle_years staging, versioning, and enrichment cache metadata

Revision ID: b2c3d4e5f6a7
Revises: 606962de4978
Create Date: 2026-06-10 00:00:00.000000+00:00

Adds:
- vehicle_years_staging       — holds enriched rows pending admin review
- vehicle_years_versions      — one record per admin-approved merge commit
- vehicle_years_changelog     — row-level diffs for rollback support
- enrichment_cache_meta       — tracks last-downloaded timestamps for fueleconomy CSV + NHTSA cache
- source column on vehicle_years — records which data source produced each row
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "606962de4978"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── source column on vehicle_years ────────────────────────────────────────
    op.add_column(
        "vehicle_years",
        sa.Column("source", sa.String(50), nullable=True),
    )

    # ── vehicle_years_staging ─────────────────────────────────────────────────
    op.create_table(
        "vehicle_years_staging",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("make", sa.String(100), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("engine_capacity", sa.Integer(), nullable=True),
        sa.Column("fuel", sa.String(50), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("staged_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_valid", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("invalid_reason", sa.Text(), nullable=True),
        sa.Column("conflict", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("conflict_detail", sa.Text(), nullable=True),
        sa.UniqueConstraint("make", "model", "year", name="uq_vehicle_years_staging_key"),
    )
    op.create_index("ix_vehicle_years_staging_run_id", "vehicle_years_staging", ["run_id"])
    op.create_index("ix_vehicle_years_staging_conflict", "vehicle_years_staging", ["conflict"])

    # ── vehicle_years_versions ────────────────────────────────────────────────
    op.create_table(
        "vehicle_years_versions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("committed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("removed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("committed_by", sa.String(100), nullable=True),
        sa.Column("initiated_by", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_vehicle_years_versions_committed_at", "vehicle_years_versions", ["committed_at"])

    # ── vehicle_years_changelog ───────────────────────────────────────────────
    op.create_table(
        "vehicle_years_changelog",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version_id", sa.Text(), sa.ForeignKey("vehicle_years_versions.id"), nullable=False),
        sa.Column("make", sa.String(100), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.Text(), nullable=False),  # 'added' | 'updated' | 'removed'
        sa.Column("old_values", sa.Text(), nullable=True),    # JSON {engine_capacity, fuel, source}
        sa.Column("new_values", sa.Text(), nullable=True),    # JSON {engine_capacity, fuel, source}
    )
    op.create_index("ix_vehicle_years_changelog_version_id", "vehicle_years_changelog", ["version_id"])

    # ── enrichment_cache_meta ─────────────────────────────────────────────────
    op.create_table(
        "enrichment_cache_meta",
        sa.Column("key", sa.Text(), primary_key=True),         # 'fueleconomy_csv' | 'year_cache'
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # Seed known cache keys so the status endpoint always finds rows
    op.execute(
        "INSERT INTO enrichment_cache_meta (key, notes) VALUES "
        "('fueleconomy_csv', 'fueleconomy.gov EPA bulk CSV (1984-present)'), "
        "('year_cache', 'NHTSA VPIC + CarAPI model lists')"
    )


def downgrade() -> None:
    op.drop_table("enrichment_cache_meta")
    op.drop_index("ix_vehicle_years_changelog_version_id", "vehicle_years_changelog")
    op.drop_table("vehicle_years_changelog")
    op.drop_index("ix_vehicle_years_versions_committed_at", "vehicle_years_versions")
    op.drop_table("vehicle_years_versions")
    op.drop_index("ix_vehicle_years_staging_conflict", "vehicle_years_staging")
    op.drop_index("ix_vehicle_years_staging_run_id", "vehicle_years_staging")
    op.drop_table("vehicle_years_staging")
    op.drop_column("vehicle_years", "source")
