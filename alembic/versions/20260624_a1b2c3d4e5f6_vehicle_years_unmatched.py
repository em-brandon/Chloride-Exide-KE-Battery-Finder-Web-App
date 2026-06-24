"""Add vehicle_years_unmatched table

Revision ID: a1b2c3d4e5f6
Revises: 219dab65024d
Create Date: 2026-06-24 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "219dab65024d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vehicle_years_unmatched",
        sa.Column("id",          sa.Integer(),               primary_key=True, autoincrement=True),
        sa.Column("run_id",      sa.Text(),                  nullable=False),
        sa.Column("make",        sa.String(100),             nullable=False),
        sa.Column("model",       sa.String(200),             nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_vehicle_years_unmatched_run_id", "vehicle_years_unmatched", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_vehicle_years_unmatched_run_id", table_name="vehicle_years_unmatched")
    op.drop_table("vehicle_years_unmatched")
