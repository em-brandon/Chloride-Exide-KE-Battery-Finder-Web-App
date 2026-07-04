"""admin tables: users, sessions, audit log, stats + battery soft delete

Revision ID: b3a9f2d1c8e4
Revises: 932c18968f61
Create Date: 2026-05-05 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b3a9f2d1c8e4'
down_revision: Union[str, None] = '932c18968f61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # admin_users
    # ------------------------------------------------------------------
    op.create_table(
        'admin_users',
        sa.Column('id',            sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('username',      sa.String(100),   nullable=False,   unique=True),
        sa.Column('password_hash', sa.String(255),   nullable=False),
        sa.Column('created_at',    sa.DateTime(timezone=True),
                  server_default=sa.text('NOW()'),   nullable=False),
    )
    op.create_index('ix_admin_users_username', 'admin_users', ['username'], unique=True)

    # ------------------------------------------------------------------
    # admin_sessions
    # ------------------------------------------------------------------
    op.create_table(
        'admin_sessions',
        sa.Column('id',            sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('session_token', sa.String(64),    nullable=False,   unique=True),
        sa.Column('admin_id',      sa.Integer(),
                  sa.ForeignKey('admin_users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at',    sa.DateTime(timezone=True),
                  server_default=sa.text('NOW()'),   nullable=False),
        sa.Column('expires_at',    sa.DateTime(timezone=True),         nullable=False),
        sa.Column('ip_address',    sa.String(45),    nullable=True),
    )
    op.create_index('ix_admin_sessions_token',    'admin_sessions', ['session_token'], unique=True)
    op.create_index('ix_admin_sessions_admin_id', 'admin_sessions', ['admin_id'])

    # ------------------------------------------------------------------
    # battery_audit_log
    # ------------------------------------------------------------------
    op.create_table(
        'battery_audit_log',
        sa.Column('id',          sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('battery_id',  sa.Integer(),
                  sa.ForeignKey('battery_specs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action',      sa.String(10),    nullable=False),   # INSERT / UPDATE / DELETE
        sa.Column('changed_by',  sa.String(100),   nullable=False),   # admin username
        sa.Column('changed_at',  sa.DateTime(timezone=True),
                  server_default=sa.text('NOW()'),  nullable=False),
        sa.Column('old_values',  sa.Text(),        nullable=True),    # JSON string
        sa.Column('new_values',  sa.Text(),        nullable=True),    # JSON string
    )
    op.create_index('ix_battery_audit_battery_id', 'battery_audit_log', ['battery_id'])
    op.create_index('ix_battery_audit_changed_at', 'battery_audit_log', ['changed_at'])

    # ------------------------------------------------------------------
    # admin_stats  (persisted counters)
    # ------------------------------------------------------------------
    op.create_table(
        'admin_stats',
        sa.Column('id',         sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('stat_key',   sa.String(100),   nullable=False,   unique=True),
        sa.Column('stat_value', sa.BigInteger(),  nullable=False,   server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_admin_stats_key', 'admin_stats', ['stat_key'], unique=True)

    # ------------------------------------------------------------------
    # battery_specs — add soft-delete column
    # ------------------------------------------------------------------
    op.add_column(
        'battery_specs',
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('battery_specs', 'deleted_at')
    op.drop_index('ix_admin_stats_key',           table_name='admin_stats')
    op.drop_table('admin_stats')
    op.drop_index('ix_battery_audit_changed_at',  table_name='battery_audit_log')
    op.drop_index('ix_battery_audit_battery_id',  table_name='battery_audit_log')
    op.drop_table('battery_audit_log')
    op.drop_index('ix_admin_sessions_admin_id',   table_name='admin_sessions')
    op.drop_index('ix_admin_sessions_token',      table_name='admin_sessions')
    op.drop_table('admin_sessions')
    op.drop_index('ix_admin_users_username',      table_name='admin_users')
    op.drop_table('admin_users')
