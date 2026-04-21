"""add tournament_polls.chat_username

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a5b6c7d8e9f0'
down_revision: Union[str, Sequence[str], None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tournament_polls',
        sa.Column('chat_username', sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('tournament_polls', 'chat_username')
