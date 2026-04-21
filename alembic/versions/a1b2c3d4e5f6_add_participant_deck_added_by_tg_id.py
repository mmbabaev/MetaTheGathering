"""add participant deck_added_by_tg_id

Revision ID: a1b2c3d4e5f6
Revises: 94843f3c9b5f
Create Date: 2026-04-21

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '94843f3c9b5f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('participants', sa.Column('deck_added_by_tg_id', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('participants', 'deck_added_by_tg_id')
