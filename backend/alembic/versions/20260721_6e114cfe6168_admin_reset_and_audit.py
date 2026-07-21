"""add email/reset-token columns to admin_users, add admin_account_audit_log

Revision ID: 6e114cfe6168
Revises: c4d5e6f7a8b9
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa

revision = '6e114cfe6168'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('admin_users', sa.Column('email', sa.String(255), nullable=True))
    op.add_column('admin_users', sa.Column('reset_token_hash', sa.String(64), nullable=True))
    op.add_column('admin_users', sa.Column('reset_token_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_admin_users_email', 'admin_users', ['email'], unique=True)

    op.create_table(
        'admin_account_audit_log',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('actor_admin_id', sa.Integer(), sa.ForeignKey('admin_users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('actor_username', sa.String(100), nullable=True),
        sa.Column('target_admin_id', sa.Integer(), sa.ForeignKey('admin_users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('target_username', sa.String(100), nullable=False),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_admin_account_audit_log_created_at', 'admin_account_audit_log', ['created_at'])


def downgrade():
    op.drop_index('ix_admin_account_audit_log_created_at', table_name='admin_account_audit_log')
    op.drop_table('admin_account_audit_log')

    op.drop_index('ix_admin_users_email', table_name='admin_users')
    op.drop_column('admin_users', 'reset_token_expires_at')
    op.drop_column('admin_users', 'reset_token_hash')
    op.drop_column('admin_users', 'email')
