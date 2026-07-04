"""add vehicle and battery fields to search_events

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = '2b3c4d5e6f7a'
down_revision = '1a2b3c4d5e6f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('search_events', sa.Column('make',             sa.String(80),  nullable=True))
    op.add_column('search_events', sa.Column('model',            sa.String(80),  nullable=True))
    op.add_column('search_events', sa.Column('year',             sa.Integer(),   nullable=True))
    op.add_column('search_events', sa.Column('engine_cc',        sa.Integer(),   nullable=True))
    op.add_column('search_events', sa.Column('fuel_type',        sa.String(20),  nullable=True))
    op.add_column('search_events', sa.Column('battery_returned', sa.String(50),  nullable=True))
    op.add_column('search_events', sa.Column('battery_ah',       sa.Integer(),   nullable=True))


def downgrade():
    op.drop_column('search_events', 'battery_ah')
    op.drop_column('search_events', 'battery_returned')
    op.drop_column('search_events', 'fuel_type')
    op.drop_column('search_events', 'engine_cc')
    op.drop_column('search_events', 'year')
    op.drop_column('search_events', 'model')
    op.drop_column('search_events', 'make')
