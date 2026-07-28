"""add admin_backup_log table

Revision ID: 4b7e9c2a1f83
Revises: 3278f8c1b881
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

revision = '4b7e9c2a1f83'
down_revision = '3278f8c1b881'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'admin_backup_log',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('error_detail', sa.Text(), nullable=True),
        sa.Column('triggered_by', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_admin_backup_log_created_at', 'admin_backup_log', ['created_at'])


def downgrade():
    op.drop_index('ix_admin_backup_log_created_at', table_name='admin_backup_log')
    op.drop_table('admin_backup_log')
