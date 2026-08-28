"""add cellar sheet fields

Revision ID: 8d26a576e45a
Revises: 6e8ac3078740
Create Date: 2026-08-22
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "8d26a576e45a"
down_revision: Union[str, Sequence[str], None] = "6e8ac3078740"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cellar_decks", sa.Column("decklist_updated_on", sa.Date(), nullable=True))
    op.add_column(
        "cellar_decks",
        sa.Column("available", sa.Boolean(), server_default="true", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("cellar_decks", "available")
    op.drop_column("cellar_decks", "decklist_updated_on")
