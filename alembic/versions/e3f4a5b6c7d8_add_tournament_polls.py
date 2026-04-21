"""add tournament_polls and poll_votes

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-04-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tournament_polls',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('tournament_id', sa.Integer(), sa.ForeignKey('tournaments.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('tg_poll_id', sa.String(), nullable=False, unique=True),
        sa.Column('message_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table(
        'poll_votes',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('poll_id', sa.Integer(), sa.ForeignKey('tournament_polls.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tg_user_id', sa.BigInteger(), nullable=False),
        sa.Column('choice', sa.Integer(), nullable=False),
        sa.UniqueConstraint('poll_id', 'tg_user_id', name='uq_poll_vote_unique'),
    )


def downgrade() -> None:
    op.drop_table('poll_votes')
    op.drop_table('tournament_polls')
