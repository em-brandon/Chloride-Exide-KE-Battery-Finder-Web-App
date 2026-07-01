"""add search_events table

Revision ID: 0369c7f9b5dc
Revises: f2a3b4c5d6e7
Create Date: 2026-07-01 11:09:24.078216+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0369c7f9b5dc'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'search_events',
        sa.Column('id',         sa.Integer(),              autoincrement=True, nullable=False),
        sa.Column('timestamp',  sa.DateTime(timezone=True),                    nullable=False),
        sa.Column('match_type', sa.String(length=50),                          nullable=True),
        sa.Column('confidence', sa.Integer(),                                   nullable=True),
        sa.Column('matched',    sa.Boolean(),                                   nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_search_events_timestamp', 'search_events', ['timestamp'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_search_events_timestamp', table_name='search_events')
    op.drop_table('search_events')
