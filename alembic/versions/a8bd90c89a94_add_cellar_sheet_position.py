"""add cellar sheet position

Revision ID: a8bd90c89a94
Revises: 8d26a576e45a
Create Date: 2026-08-22
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a8bd90c89a94"
down_revision: Union[str, Sequence[str], None] = "8d26a576e45a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cellar_decks", sa.Column("source_position", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("cellar_decks", "source_position")
