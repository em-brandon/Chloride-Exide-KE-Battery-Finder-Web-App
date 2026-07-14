"""add oem_fitment and vehicle_years_exide tables

Revision ID: c1d2e3f4a5b6
Revises: f4a5b6c7d8e9
Create Date: 2026-07-14 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oem_fitment",
        sa.Column("id",                   sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column("vehicle_category",     sa.String(20),    nullable=False),
        sa.Column("make",                 sa.String(100),   nullable=False),
        sa.Column("model",                sa.String(300),   nullable=False),
        sa.Column("year_from",            sa.Integer(),     nullable=False),
        sa.Column("year_to",              sa.Integer(),     nullable=True),
        sa.Column("ah",                   sa.Float(),       nullable=True),
        sa.Column("technology",           sa.String(50),    nullable=True),
        sa.Column("raw_technology",       sa.String(50),    nullable=True),
        sa.Column("dimensions",           sa.String(50),    nullable=True),
        sa.Column("cylinder_capacity_cc", sa.Integer(),     nullable=True),
        sa.Column("source_row",           sa.Integer(),     nullable=True),
        sa.UniqueConstraint(
            "make", "model", "vehicle_category", "year_from", "year_to", "ah", "technology",
            name="uq_oem_fitment",
        ),
    )
    op.create_index("ix_oem_fitment_make", "oem_fitment", ["make"])
    op.create_index("ix_oem_fitment_make_model", "oem_fitment", ["make", "model"])

    op.create_table(
        "vehicle_years_exide",
        sa.Column("id",              sa.Integer(),   primary_key=True, autoincrement=True),
        sa.Column("make",            sa.String(100), nullable=False),
        sa.Column("model",           sa.String(300), nullable=False),
        sa.Column("year",            sa.Integer(),   nullable=False),
        sa.Column("engine_capacity", sa.Integer(),   nullable=True),
        sa.Column("fuel",            sa.String(50),  nullable=True),
        sa.UniqueConstraint("make", "model", "year", name="uq_vehicle_years_exide"),
    )
    op.create_index("ix_vehicle_years_exide_make", "vehicle_years_exide", ["make"])
    op.create_index("ix_vehicle_years_exide_make_model", "vehicle_years_exide", ["make", "model"])


def downgrade() -> None:
    op.drop_index("ix_vehicle_years_exide_make_model", table_name="vehicle_years_exide")
    op.drop_index("ix_vehicle_years_exide_make",       table_name="vehicle_years_exide")
    op.drop_table("vehicle_years_exide")

    op.drop_index("ix_oem_fitment_make_model", table_name="oem_fitment")
    op.drop_index("ix_oem_fitment_make",       table_name="oem_fitment")
    op.drop_table("oem_fitment")
