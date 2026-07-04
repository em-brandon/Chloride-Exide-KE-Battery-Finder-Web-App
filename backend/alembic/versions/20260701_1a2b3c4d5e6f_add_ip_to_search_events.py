"""add ip_address to search_events

Revision ID: 1a2b3c4d5e6f
Revises: 0369c7f9b5dc
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = '1a2b3c4d5e6f'
down_revision = '0369c7f9b5dc'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('search_events', sa.Column('ip_address', sa.String(45), nullable=True))


def downgrade():
    op.drop_column('search_events', 'ip_address')
