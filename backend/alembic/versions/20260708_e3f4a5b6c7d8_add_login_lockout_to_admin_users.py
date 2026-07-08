"""add failed_login_attempts and locked_until to admin_users

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa

revision = 'e3f4a5b6c7d8'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('admin_users', sa.Column('failed_login_attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('admin_users', sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('admin_users', 'locked_until')
    op.drop_column('admin_users', 'failed_login_attempts')
