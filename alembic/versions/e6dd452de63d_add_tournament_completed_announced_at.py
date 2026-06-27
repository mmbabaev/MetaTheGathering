"""add tournament.completed_announced_at

Revision ID: e6dd452de63d
Revises: 40f49c4eba55
Create Date: 2026-06-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6dd452de63d'
down_revision: Union[str, Sequence[str], None] = '40f49c4eba55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tournaments',
        sa.Column('completed_announced_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('tournaments', 'completed_announced_at')
