"""add participant.final_place

Revision ID: e0f1a2b3c4d5
Revises: b5c6d7e8f9a0
Create Date: 2026-05-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e0f1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'b5c6d7e8f9a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'participants',
        sa.Column('final_place', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('participants', 'final_place')
