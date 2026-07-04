"""Add fueleconomy_vehicles table

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-24 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fueleconomy_vehicles",
        sa.Column("id",    sa.Integer(),   primary_key=True, autoincrement=True),
        sa.Column("year",  sa.Integer(),   nullable=False),
        sa.Column("make",  sa.String(100), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
    )
    op.create_index("ix_fueleconomy_vehicles_make_model", "fueleconomy_vehicles", ["make", "model"])


def downgrade() -> None:
    op.drop_index("ix_fueleconomy_vehicles_make_model", table_name="fueleconomy_vehicles")
    op.drop_table("fueleconomy_vehicles")
