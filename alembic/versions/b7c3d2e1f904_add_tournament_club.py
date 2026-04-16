"""add_tournament_club

Revision ID: b7c3d2e1f904
Revises: a3f2e1b9c804
Create Date: 2026-04-16 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c3d2e1f904'
down_revision: Union[str, Sequence[str], None] = 'a3f2e1b9c804'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tournaments', sa.Column('club', sa.String(length=64), nullable=True))
    op.create_index('ix_tournaments_club', 'tournaments', ['club'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_tournaments_club', table_name='tournaments')
    op.drop_column('tournaments', 'club')
