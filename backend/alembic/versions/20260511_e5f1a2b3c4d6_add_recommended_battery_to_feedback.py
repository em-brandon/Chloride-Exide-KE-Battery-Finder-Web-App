"""add recommended_battery to user_feedback

Revision ID: e5f1a2b3c4d6
Revises: d4e2f8a1b3c6
Create Date: 2026-05-11

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = 'e5f1a2b3c4d6'
down_revision = 'd4e2f8a1b3c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'user_feedback',
        sa.Column('recommended_battery', sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('user_feedback', 'recommended_battery')
