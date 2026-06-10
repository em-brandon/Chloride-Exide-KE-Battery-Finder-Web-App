"""quota 30-day rolling period columns

Revision ID: a1b2c3d4e5f6
Revises: 6259d46ad841
Create Date: 2026-06-10 00:00:00.000000+00:00

Adds period_start and period_end to api_usage_quota so quotas reset every
30 calendar days from first use rather than on calendar-month boundaries.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "6259d46ad841"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("api_usage_quota",
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True))
    op.add_column("api_usage_quota",
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True))

    # Backfill existing rows: period starts at the beginning of their month,
    # ends 30 days later.
    op.execute("""
        UPDATE api_usage_quota
        SET period_start = date_trunc('month', updated_at AT TIME ZONE 'UTC'),
            period_end   = date_trunc('month', updated_at AT TIME ZONE 'UTC')
                           + INTERVAL '30 days'
        WHERE period_start IS NULL
    """)


def downgrade() -> None:
    op.drop_column("api_usage_quota", "period_end")
    op.drop_column("api_usage_quota", "period_start")
