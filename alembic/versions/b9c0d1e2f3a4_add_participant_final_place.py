"""add participant.final_place

Revision ID: b9c0d1e2f3a4
Revises: d5e6f7a8b9c0
Create Date: 2026-05-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'participants',
        sa.Column('final_place', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('participants', 'final_place')
