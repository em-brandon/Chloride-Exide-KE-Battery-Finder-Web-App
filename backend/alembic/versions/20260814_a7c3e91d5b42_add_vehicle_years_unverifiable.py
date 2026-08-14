"""add vehicle_years_unverifiable quarantine table

Holds (make, model, year) rows moved out of vehicle_years because no
automated source could confirm the nameplate's real production years. These
need manual research; the table is the worklist as well as the parking spot,
so a row can be moved back verbatim once a human settles its years.

Deliberately NOT granted to the batteryfinder_public role (see migration
20260721_c4d5e6f7a8b9): quarantined rows must not reach the matcher.

Revision ID: a7c3e91d5b42
Revises: fc5fac9ccee3
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

revision = 'a7c3e91d5b42'
down_revision = 'fc5fac9ccee3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'vehicle_years_unverifiable',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('make', sa.String(length=100), nullable=False),
        sa.Column('model', sa.String(length=200), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('engine_capacity', sa.Integer(), nullable=True),
        sa.Column('fuel', sa.String(length=50), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.Column('model_number', sa.String(length=100), nullable=True),
        # Nameplate the row was grouped under, plus why research stalled —
        # both are what makes this table usable as a research worklist rather
        # than just a dumping ground.
        sa.Column('base_model', sa.String(length=200), nullable=True),
        sa.Column('reason', sa.String(length=64), nullable=True),
        sa.Column('moved_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('batch_id', sa.String(length=64), nullable=True),
        sa.UniqueConstraint('make', 'model', 'year', name='uq_vehicle_years_unverifiable'),
    )
    op.create_index('ix_vehicle_years_unverifiable_make', 'vehicle_years_unverifiable', ['make'])
    op.create_index('ix_vehicle_years_unverifiable_reason', 'vehicle_years_unverifiable', ['reason'])
    op.create_index('ix_vehicle_years_unverifiable_batch', 'vehicle_years_unverifiable', ['batch_id'])


def downgrade() -> None:
    op.drop_index('ix_vehicle_years_unverifiable_batch', table_name='vehicle_years_unverifiable')
    op.drop_index('ix_vehicle_years_unverifiable_reason', table_name='vehicle_years_unverifiable')
    op.drop_index('ix_vehicle_years_unverifiable_make', table_name='vehicle_years_unverifiable')
    op.drop_table('vehicle_years_unverifiable')
