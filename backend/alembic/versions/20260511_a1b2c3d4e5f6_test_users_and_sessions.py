"""test_users, test_user_sessions tables; user_feedback.test_user_id FK

Revision ID: a1b2c3d4e5f6
Revises: c7e1f9a2b3d5
Create Date: 2026-05-11 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'c7e1f9a2b3d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── test_users ────────────────────────────────────────────────────────────
    op.create_table(
        'test_users',
        sa.Column('id',            sa.Integer(),              autoincrement=True, nullable=False),
        sa.Column('username',      sa.String(length=100),     nullable=False),
        sa.Column('email',         sa.String(length=255),     nullable=True),
        sa.Column('password_hash', sa.String(length=255),     nullable=False),
        sa.Column('created_at',    sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_active',     sa.Integer(),              nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
        sa.UniqueConstraint('email'),
    )
    op.create_index('ix_test_users_username', 'test_users', ['username'], unique=True)

    # ── test_user_sessions ────────────────────────────────────────────────────
    op.create_table(
        'test_user_sessions',
        sa.Column('id',            sa.Integer(),              autoincrement=True, nullable=False),
        sa.Column('session_token', sa.String(length=64),      nullable=False),
        sa.Column('user_id',       sa.Integer(),              nullable=False),
        sa.Column('created_at',    sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at',    sa.DateTime(timezone=True), nullable=False),
        sa.Column('ip_address',    sa.String(length=45),      nullable=True),
        sa.Column('user_agent',    sa.String(length=300),     nullable=True),
        sa.Column('last_seen_at',  sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['test_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_token'),
    )
    op.create_index('ix_test_user_sessions_token',   'test_user_sessions', ['session_token'], unique=True)
    op.create_index('ix_test_user_sessions_user_id', 'test_user_sessions', ['user_id'],       unique=False)

    # ── user_feedback.test_user_id FK ────────────────────────────────────────
    op.add_column(
        'user_feedback',
        sa.Column('test_user_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_user_feedback_test_user_id',
        'user_feedback', 'test_users',
        ['test_user_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_user_feedback_test_user_id', 'user_feedback', type_='foreignkey')
    op.drop_column('user_feedback', 'test_user_id')
    op.drop_index('ix_test_user_sessions_user_id', table_name='test_user_sessions')
    op.drop_index('ix_test_user_sessions_token',   table_name='test_user_sessions')
    op.drop_table('test_user_sessions')
    op.drop_index('ix_test_users_username', table_name='test_users')
    op.drop_table('test_users')
