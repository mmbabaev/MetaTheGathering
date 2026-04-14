"""add_user_deck_history

Revision ID: a3f2e1b9c804
Revises: 1413b684d806
Create Date: 2026-04-14 08:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f2e1b9c804'
down_revision: Union[str, Sequence[str], None] = '1413b684d806'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_deck_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('archetype_id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['archetype_id'], ['archetypes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'archetype_id', name='uq_user_deck_history'),
    )
    op.create_index('ix_user_deck_history_id', 'user_deck_history', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_user_deck_history_id', table_name='user_deck_history')
    op.drop_table('user_deck_history')
