"""track meta-police reminder message

Revision ID: 5b3f291c06a3
Revises: 5132b26f0434
Create Date: 2026-08-27
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "5b3f291c06a3"
down_revision: Union[str, Sequence[str], None] = "5132b26f0434"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tournaments", sa.Column("missing_decks_reminder_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("tournaments", sa.Column("missing_decks_reminder_message_id", sa.BigInteger(), nullable=True))
    op.add_column("tournaments", sa.Column("missing_decks_reminder_participant_ids", sa.Text(), nullable=True))
    op.add_column("tournaments", sa.Column("missing_decks_reminder_button_url", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("tournaments", "missing_decks_reminder_button_url")
    op.drop_column("tournaments", "missing_decks_reminder_participant_ids")
    op.drop_column("tournaments", "missing_decks_reminder_message_id")
    op.drop_column("tournaments", "missing_decks_reminder_chat_id")
