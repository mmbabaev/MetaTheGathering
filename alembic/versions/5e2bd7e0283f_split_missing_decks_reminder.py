"""split missing decks reminder into day one and day three

Revision ID: 5e2bd7e0283f
Revises: b8dcffe21093
Create Date: 2026-08-16
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "5e2bd7e0283f"
down_revision: Union[str, Sequence[str], None] = "b8dcffe21093"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tournaments", sa.Column("missing_decks_reminder_1d_sent_at", sa.DateTime(), nullable=True))
    op.add_column("tournaments", sa.Column("missing_decks_reminder_3d_sent_at", sa.DateTime(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE tournaments "
            "SET missing_decks_reminder_1d_sent_at = missing_decks_reminder_sent_at, "
            "missing_decks_reminder_3d_sent_at = missing_decks_reminder_sent_at "
            "WHERE missing_decks_reminder_sent_at IS NOT NULL"
        )
    )
    op.drop_column("tournaments", "missing_decks_reminder_sent_at")


def downgrade() -> None:
    op.add_column("tournaments", sa.Column("missing_decks_reminder_sent_at", sa.DateTime(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE tournaments "
            "SET missing_decks_reminder_sent_at = COALESCE("
            "missing_decks_reminder_3d_sent_at, missing_decks_reminder_1d_sent_at)"
        )
    )
    op.drop_column("tournaments", "missing_decks_reminder_3d_sent_at")
    op.drop_column("tournaments", "missing_decks_reminder_1d_sent_at")
