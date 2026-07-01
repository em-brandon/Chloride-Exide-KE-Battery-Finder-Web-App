"""add perf indexes: search_events match_type, battery_specs partial active, search_events autovacuum

Revision ID: 3c4d5e6f7a8b
Revises: 2b3c4d5e6f7a
Create Date: 2026-07-01
"""
from alembic import op

revision = '3c4d5e6f7a8b'
down_revision = '2b3c4d5e6f7a'
branch_labels = None
depends_on = None


def upgrade():
    # Index for match_type filter on search log page
    op.create_index('ix_search_events_match_type', 'search_events', ['match_type'])

    # Partial index covering only active (non-deleted) batteries —
    # all admin queries and the matcher filter deleted_at IS NULL
    op.execute(
        "CREATE INDEX ix_battery_specs_active ON battery_specs (id) WHERE deleted_at IS NULL"
    )

    # Lower autovacuum analyze threshold for search_events from 20% → 5%
    # so planner statistics stay fresh as the append-only log grows
    op.execute(
        "ALTER TABLE search_events SET (autovacuum_analyze_scale_factor = 0.05)"
    )


def downgrade():
    op.drop_index('ix_search_events_match_type', table_name='search_events')
    op.execute("DROP INDEX IF EXISTS ix_battery_specs_active")
    op.execute(
        "ALTER TABLE search_events RESET (autovacuum_analyze_scale_factor)"
    )
