"""add dial_battery_inference table

Revision ID: a7b2c3d4e5f6
Revises: f6a1b2c3d4e5
Create Date: 2026-05-26 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b2c3d4e5f6"
down_revision: Union[str, None] = "f6a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dial_battery_inference",
        sa.Column("id",           sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column("vehicle_type", sa.Text(),         nullable=False),
        sa.Column("vehicle_model",sa.Text(),         nullable=False),
        sa.Column("battery_code", sa.Text(),         nullable=False),
        sa.Column("frequency",    sa.Integer(),      nullable=False, server_default="1"),
        sa.UniqueConstraint("vehicle_type", "vehicle_model", "battery_code",
                            name="uq_dial_battery_inference"),
    )
    op.create_index(
        "ix_dial_battery_inference_make",
        "dial_battery_inference",
        ["vehicle_type"],
    )
    op.create_index(
        "ix_dial_battery_inference_make_model",
        "dial_battery_inference",
        ["vehicle_type", "vehicle_model"],
    )


def downgrade() -> None:
    op.drop_index("ix_dial_battery_inference_make_model", table_name="dial_battery_inference")
    op.drop_index("ix_dial_battery_inference_make",       table_name="dial_battery_inference")
    op.drop_table("dial_battery_inference")
