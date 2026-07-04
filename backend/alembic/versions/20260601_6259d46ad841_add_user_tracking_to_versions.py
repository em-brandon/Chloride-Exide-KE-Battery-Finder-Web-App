"""add_user_tracking_to_versions

Revision ID: 6259d46ad841
Revises: b3c4d5e6f7a8
Create Date: 2026-06-01 14:08:23.259711+00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '6259d46ad841'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('web_battery_validation_versions', sa.Column('committed_by', sa.Text(), nullable=True))
    op.add_column('web_battery_validation_versions', sa.Column('initiated_by', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('web_battery_validation_versions', 'initiated_by')
    op.drop_column('web_battery_validation_versions', 'committed_by')
