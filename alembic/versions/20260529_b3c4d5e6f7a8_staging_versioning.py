"""Add staging area, versioning, pipeline run log, and vehicle timestamps

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-05-29 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Add run_id + version_id to the master table
    # ------------------------------------------------------------------
    op.add_column(
        "web_battery_validation",
        sa.Column("run_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "web_battery_validation",
        sa.Column("version_id", sa.Text(), nullable=True),
    )

    # ------------------------------------------------------------------
    # 2. Staging table — temporary holding area for stopped runs
    # ------------------------------------------------------------------
    op.create_table(
        "web_battery_staging",
        sa.Column("id",             sa.Integer(),                             primary_key=True, autoincrement=True),
        sa.Column("run_id",         sa.Text(),                                nullable=False),
        sa.Column("make_n",         sa.Text(),                                nullable=False),
        sa.Column("model_n",        sa.Text(),                                nullable=False),
        sa.Column("year",           sa.Integer(),                             nullable=False),
        sa.Column("battery_code",   sa.Text(),                                nullable=True),
        sa.Column("ah",             sa.Integer(),                             nullable=True),
        sa.Column("technology",     sa.Text(),                                nullable=True),
        sa.Column("source",         sa.Text(),                                nullable=True),
        sa.Column("engine_cc",      sa.Integer(),                             nullable=True),
        sa.Column("fuel_type",      sa.Text(),                                nullable=True),
        sa.Column("staged_at",      sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_valid",       sa.Boolean(),                             nullable=False, server_default=sa.true()),
        sa.Column("invalid_reason", sa.Text(),                                nullable=True),
        sa.Column("conflict",       sa.Boolean(),                             nullable=False, server_default=sa.false()),
        sa.Column("conflict_detail", sa.Text(),                               nullable=True),   # JSON stored as text
        sa.UniqueConstraint("make_n", "model_n", "year", name="uq_web_battery_staging"),
    )

    # ------------------------------------------------------------------
    # 3. Versions table — one row per committed merge
    # ------------------------------------------------------------------
    op.create_table(
        "web_battery_validation_versions",
        sa.Column("id",              sa.Text(),     primary_key=True),   # UUID string
        sa.Column("version_number",  sa.Integer(),  nullable=False),
        sa.Column("committed_at",    sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("run_id",          sa.Text(),     nullable=True),
        sa.Column("committed_count", sa.Integer(),  nullable=False, server_default="0"),
        sa.Column("removed_count",   sa.Integer(),  nullable=False, server_default="0"),
        sa.Column("conflict_count",  sa.Integer(),  nullable=False, server_default="0"),
        sa.Column("notes",           sa.Text(),     nullable=True),
    )
    op.create_index(
        "ix_wbv_versions_committed_at",
        "web_battery_validation_versions",
        ["committed_at"],
    )

    # ------------------------------------------------------------------
    # 4. Changelog table — row-level diff per version
    # ------------------------------------------------------------------
    op.create_table(
        "web_battery_validation_changelog",
        sa.Column("id",          sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version_id",  sa.Text(),    nullable=False),
        sa.Column("make_n",      sa.Text(),    nullable=False),
        sa.Column("model_n",     sa.Text(),    nullable=False),
        sa.Column("year",        sa.Integer(), nullable=False),
        sa.Column("change_type", sa.Text(),    nullable=False),  # 'added' | 'updated' | 'removed'
        sa.Column("old_values",  sa.Text(),    nullable=True),   # JSON
        sa.Column("new_values",  sa.Text(),    nullable=True),   # JSON
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["web_battery_validation_versions.id"],
            name="fk_changelog_version",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_wbv_changelog_version_id",
        "web_battery_validation_changelog",
        ["version_id"],
    )

    # ------------------------------------------------------------------
    # 5. Pipeline run log — tracks each run completion for staleness checks
    # ------------------------------------------------------------------
    op.create_table(
        "pipeline_run_log",
        sa.Column("id",               sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id",           sa.Text(),    nullable=False),
        sa.Column("status",           sa.Text(),    nullable=False),  # 'completed' | 'cancelled' | 'error'
        sa.Column("finished_at",      sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("combos_processed", sa.Integer(), nullable=True),
        sa.Column("combos_matched",   sa.Integer(), nullable=True),
    )

    # ------------------------------------------------------------------
    # 6. Add created_at / updated_at to vehicle_years for staleness detection
    # ------------------------------------------------------------------
    op.add_column(
        "vehicle_years",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )
    op.add_column(
        "vehicle_years",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("vehicle_years", "updated_at")
    op.drop_column("vehicle_years", "created_at")
    op.drop_table("pipeline_run_log")
    op.drop_index("ix_wbv_changelog_version_id", table_name="web_battery_validation_changelog")
    op.drop_table("web_battery_validation_changelog")
    op.drop_index("ix_wbv_versions_committed_at", table_name="web_battery_validation_versions")
    op.drop_table("web_battery_validation_versions")
    op.drop_table("web_battery_staging")
    op.drop_column("web_battery_validation", "version_id")
    op.drop_column("web_battery_validation", "run_id")
