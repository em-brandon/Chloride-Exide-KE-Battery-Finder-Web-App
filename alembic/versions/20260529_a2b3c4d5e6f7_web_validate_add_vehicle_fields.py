"""web_battery_validation: add engine_cc and fuel_type columns

Revision ID: a2b3c4d5e6f7
Revises: d1e2f3a4b5c6
Create Date: 2026-05-29 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable so existing rows are unaffected; populated on next pipeline run.
    op.add_column("web_battery_validation", sa.Column("engine_cc",  sa.Integer(), nullable=True))
    op.add_column("web_battery_validation", sa.Column("fuel_type",  sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("web_battery_validation", "fuel_type")
    op.drop_column("web_battery_validation", "engine_cc")
