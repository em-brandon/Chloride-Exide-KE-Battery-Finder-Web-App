"""add model_number to vehicle_years

Revision ID: fc5fac9ccee3
Revises: 4b7e9c2a1f83
Create Date: 2026-08-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'fc5fac9ccee3'
down_revision = '4b7e9c2a1f83'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('vehicle_years', sa.Column('model_number', sa.String(100), nullable=True))
    op.add_column('vehicle_years_staging', sa.Column('model_number', sa.String(100), nullable=True))


def downgrade():
    op.drop_column('vehicle_years_staging', 'model_number')
    op.drop_column('vehicle_years', 'model_number')
