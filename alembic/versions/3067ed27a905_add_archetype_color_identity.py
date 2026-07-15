"""add archetype.color_identity

Revision ID: 3067ed27a905
Revises: e6dd452de63d
Create Date: 2026-07-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3067ed27a905'
down_revision: Union[str, Sequence[str], None] = 'e6dd452de63d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'archetypes',
        sa.Column('color_identity', sa.String(length=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('archetypes', 'color_identity')
