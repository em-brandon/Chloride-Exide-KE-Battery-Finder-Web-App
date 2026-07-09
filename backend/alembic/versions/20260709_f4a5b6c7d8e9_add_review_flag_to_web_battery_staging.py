"""Add flagged/flag_reason columns to web_battery_staging for manual review

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-07-09 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Soft review flag — distinct from is_valid (which excludes a row from
    # commit). A flagged row is still valid and still gets committed; it's
    # just surfaced for a human to sanity-check before/after commit (e.g. a
    # suspiciously low Ah for a luxury make).
    op.add_column(
        "web_battery_staging",
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "web_battery_staging",
        sa.Column("flag_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("web_battery_staging", "flag_reason")
    op.drop_column("web_battery_staging", "flagged")
