"""add last_sale_date to dial_battery_inference

Revision ID: b8c3d4e5f6a7
Revises: a7b2c3d4e5f6
Create Date: 2026-05-26 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c3d4e5f6a7"
down_revision: Union[str, None] = "a7b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dial_battery_inference",
        sa.Column("last_sale_date", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dial_battery_inference", "last_sale_date")
