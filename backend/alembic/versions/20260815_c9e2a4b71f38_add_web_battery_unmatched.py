"""add web_battery_unmatched quarantine table

Rows pulled out of web_battery_staging/validation by the report-readiness gate
because their scraped Ah could not be defended against the engine-size rules.
Mirrors vehicle_years_unverifiable: quarantine rather than delete, so the row
is both recoverable and a research worklist entry.

Not granted to batteryfinder_public — quarantined rows must never reach the
matcher.

Revision ID: c9e2a4b71f38
Revises: b8d4f02e6c17
Create Date: 2026-08-15
"""
from alembic import op
import sqlalchemy as sa

revision = "c9e2a4b71f38"
down_revision = "b8d4f02e6c17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "web_battery_unmatched",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("make_n", sa.String(length=100), nullable=False),
        sa.Column("model_n", sa.String(length=200), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("ah", sa.Integer(), nullable=True),
        sa.Column("expected_ah", sa.Integer(), nullable=True),
        sa.Column("engine_cc", sa.Integer(), nullable=True),
        sa.Column("fuel_type", sa.String(length=50), nullable=True),
        sa.Column("battery_code", sa.String(length=120), nullable=True),
        sa.Column("technology", sa.String(length=50), nullable=True),
        sa.Column("source_table", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("moved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_web_battery_unmatched_batch",
                    "web_battery_unmatched", ["batch_id"])
    op.create_index("ix_web_battery_unmatched_key",
                    "web_battery_unmatched", ["make_n", "model_n", "year"])


def downgrade() -> None:
    op.drop_index("ix_web_battery_unmatched_key", table_name="web_battery_unmatched")
    op.drop_index("ix_web_battery_unmatched_batch", table_name="web_battery_unmatched")
    op.drop_table("web_battery_unmatched")
