"""add round_pairings.table_number

Revision ID: aac3d24c4e09
Revises: f6a7b8c9d0e1
Create Date: 2026-06-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'aac3d24c4e09'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('round_pairings', sa.Column('table_number', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('round_pairings', 'table_number')
