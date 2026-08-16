"""add missing decks reminder timestamp

Revision ID: b8dcffe21093
Revises: 266ab09f6f31
Create Date: 2026-08-16
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b8dcffe21093"
down_revision: Union[str, Sequence[str], None] = "266ab09f6f31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tournaments", sa.Column("missing_decks_reminder_sent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("tournaments", "missing_decks_reminder_sent_at")
