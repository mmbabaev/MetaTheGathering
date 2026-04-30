"""add user.hide_deck_emoji

Revision ID: b5c6d7e8f9a0
Revises: a1b2c3d4e5f6, a2b3c4d5e6f7
Create Date: 2026-04-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = ("a1b2c3d4e5f6", "a2b3c4d5e6f7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("hide_deck_emoji", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("users", "hide_deck_emoji")
