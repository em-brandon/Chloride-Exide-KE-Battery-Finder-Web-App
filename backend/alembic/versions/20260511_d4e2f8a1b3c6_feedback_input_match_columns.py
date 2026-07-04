"""Add input_type, match_confidence, match_type to user_feedback

Revision ID: d4e2f8a1b3c6
Revises: c7e1f9a2b3d5
Create Date: 2026-05-11 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4e2f8a1b3c6'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_feedback', sa.Column('input_type',       sa.String(20),  nullable=True))
    op.add_column('user_feedback', sa.Column('match_confidence', sa.Integer(),   nullable=True))
    op.add_column('user_feedback', sa.Column('match_type',       sa.String(50),  nullable=True))


def downgrade() -> None:
    op.drop_column('user_feedback', 'match_type')
    op.drop_column('user_feedback', 'match_confidence')
    op.drop_column('user_feedback', 'input_type')
