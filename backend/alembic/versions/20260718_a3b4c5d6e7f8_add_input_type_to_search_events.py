"""add input_type to search_events

Revision ID: a3b4c5d6e7f8
Revises: c1d2e3f4a5b6
Create Date: 2026-07-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'a3b4c5d6e7f8'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('search_events', sa.Column('input_type', sa.String(20), nullable=True))


def downgrade():
    op.drop_column('search_events', 'input_type')
