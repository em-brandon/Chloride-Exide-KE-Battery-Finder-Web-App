"""add web_battery_validation table

Revision ID: c9d4e5f6a7b8
Revises: b8c3d4e5f6a7
Create Date: 2026-05-27 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d4e5f6a7b8"
down_revision: Union[str, None] = "b8c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "web_battery_validation",
        sa.Column("id",           sa.Integer(),                              primary_key=True, autoincrement=True),
        sa.Column("make_n",       sa.Text(),                                 nullable=False),
        sa.Column("model_n",      sa.Text(),                                 nullable=False),
        sa.Column("year",         sa.Integer(),                              nullable=False),
        sa.Column("battery_code", sa.Text(),                                 nullable=False),
        sa.Column("ah",           sa.Integer(),                              nullable=True),
        sa.Column("technology",   sa.Text(),                                 nullable=True),
        sa.Column("source",       sa.Text(),                                 nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("make_n", "model_n", "year", name="uq_web_battery_validation"),
    )
    op.create_index(
        "ix_web_battery_validation_make",
        "web_battery_validation",
        ["make_n"],
    )
    op.create_index(
        "ix_web_battery_validation_make_model",
        "web_battery_validation",
        ["make_n", "model_n"],
    )


def downgrade() -> None:
    op.drop_index("ix_web_battery_validation_make_model", table_name="web_battery_validation")
    op.drop_index("ix_web_battery_validation_make",       table_name="web_battery_validation")
    op.drop_table("web_battery_validation")
