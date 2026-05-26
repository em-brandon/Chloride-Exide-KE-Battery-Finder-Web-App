"""add origin and brand to battery_specs

Revision ID: f6a1b2c3d4e5
Revises: e5f1a2b3c4d6
Create Date: 2026-05-25 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a1b2c3d4e5'
down_revision: Union[str, None] = 'e5f1a2b3c4d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('battery_specs', sa.Column('origin', sa.String(length=50), nullable=True))
    op.add_column('battery_specs', sa.Column('brand',  sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('battery_specs', 'brand')
    op.drop_column('battery_specs', 'origin')
