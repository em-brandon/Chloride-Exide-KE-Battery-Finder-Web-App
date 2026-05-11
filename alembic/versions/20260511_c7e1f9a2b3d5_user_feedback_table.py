"""user_feedback table

Revision ID: c7e1f9a2b3d5
Revises: b3a9f2d1c8e4
Create Date: 2026-05-11 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c7e1f9a2b3d5'
down_revision: Union[str, None] = 'b3a9f2d1c8e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_feedback',
        sa.Column('id',            sa.Integer(),              primary_key=True, autoincrement=True),
        sa.Column('vehicle_label', sa.String(300),            nullable=False),
        sa.Column('satisfaction',  sa.Integer(),              nullable=False),
        sa.Column('accuracy',      sa.String(20),             nullable=True),
        sa.Column('wrong_parts',   sa.Text(),                 nullable=True),
        sa.Column('comments',      sa.Text(),                 nullable=True),
        sa.Column('submitted_at',  sa.DateTime(timezone=True), nullable=False),
        sa.Column('ip_address',    sa.String(45),             nullable=True),
    )
    op.create_index('ix_user_feedback_submitted_at', 'user_feedback', ['submitted_at'])
    op.create_index('ix_user_feedback_accuracy',     'user_feedback', ['accuracy'])


def downgrade() -> None:
    op.drop_index('ix_user_feedback_accuracy',     table_name='user_feedback')
    op.drop_index('ix_user_feedback_submitted_at', table_name='user_feedback')
    op.drop_table('user_feedback')
