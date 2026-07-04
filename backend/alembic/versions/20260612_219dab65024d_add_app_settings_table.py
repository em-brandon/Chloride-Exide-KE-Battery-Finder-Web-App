"""add_app_settings_table

Revision ID: 219dab65024d
Revises: b2c3d4e5f6a7
Create Date: 2026-06-12 18:05:12.767732+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '219dab65024d'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'app_settings',
        sa.Column('id',            sa.Integer(),              autoincrement=True, nullable=False),
        sa.Column('setting_key',   sa.String(length=100),     nullable=False),
        sa.Column('setting_value', sa.String(length=500),     nullable=False),
        sa.Column('updated_at',    sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_by',    sa.String(length=100),     nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('setting_key'),
    )
    op.create_index('ix_app_settings_key', 'app_settings', ['setting_key'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_app_settings_key', table_name='app_settings')
    op.drop_table('app_settings')
