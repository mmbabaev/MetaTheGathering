"""track editable meta-police message

Revision ID: a6fbdbee0220
Revises: 5132b26f0434
Create Date: 2026-08-22
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a6fbdbee0220"
down_revision: Union[str, Sequence[str], None] = "5132b26f0434"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tournament_missing_decks_reminders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("participant_ids_json", sa.Text(), nullable=False),
        sa.Column("button_url", sa.String(length=512), nullable=True),
        sa.Column("edit_disabled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tournament_missing_decks_reminders_tournament_id",
        "tournament_missing_decks_reminders",
        ["tournament_id"],
        unique=True,
    )
    op.create_index(
        "ix_tournament_missing_decks_reminders_edit_disabled_at",
        "tournament_missing_decks_reminders",
        ["edit_disabled_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tournament_missing_decks_reminders_edit_disabled_at",
        table_name="tournament_missing_decks_reminders",
    )
    op.drop_index(
        "ix_tournament_missing_decks_reminders_tournament_id",
        table_name="tournament_missing_decks_reminders",
    )
    op.drop_table("tournament_missing_decks_reminders")
