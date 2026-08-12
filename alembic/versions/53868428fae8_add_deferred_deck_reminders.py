"""add deferred deck reminder state

Revision ID: 53868428fae8
Revises: 2a5b53ae1edf
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "53868428fae8"
down_revision: Union[str, Sequence[str], None] = "2a5b53ae1edf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "participants",
        sa.Column("deck_deferred", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "participants",
        sa.Column("deck_reminder_prestart_sent_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "participants",
        sa.Column("deck_reminder_round2_sent_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("participants", "deck_reminder_round2_sent_at")
    op.drop_column("participants", "deck_reminder_prestart_sent_at")
    op.drop_column("participants", "deck_deferred")
