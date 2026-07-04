"""add api_usage_quota table

Revision ID: d1e2f3a4b5c6
Revises: c9d4e5f6a7b8
Create Date: 2026-05-29 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c9d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_usage_quota",
        sa.Column("id",          sa.Integer(),                              primary_key=True, autoincrement=True),
        sa.Column("provider",    sa.String(50),                             nullable=False),
        sa.Column("month",       sa.String(7),                              nullable=False),   # "YYYY-MM"
        sa.Column("calls_made",  sa.Integer(),  server_default="0",         nullable=False),
        sa.Column("quota_limit", sa.Integer(),  server_default="-1",        nullable=False),   # -1 = unlimited
        sa.Column("updated_at",  sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "month", name="uq_api_usage_quota_provider_month"),
    )
    op.create_index(
        "ix_api_usage_quota_provider_month",
        "api_usage_quota",
        ["provider", "month"],
    )


def downgrade() -> None:
    op.drop_index("ix_api_usage_quota_provider_month", table_name="api_usage_quota")
    op.drop_table("api_usage_quota")
