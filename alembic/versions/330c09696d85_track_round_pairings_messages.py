"""track editable round pairings messages

Revision ID: 330c09696d85
Revises: 462d69c18f40
Create Date: 2026-09-04
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "330c09696d85"
down_revision: Union[str, Sequence[str], None] = "462d69c18f40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tournament_round_pairings_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("edit_disabled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tournament_id", "round_number", name="uq_tournament_round_pairings_message"),
    )
    op.create_index(
        "ix_tournament_round_pairings_messages_tournament_id",
        "tournament_round_pairings_messages",
        ["tournament_id"],
        unique=False,
    )
    op.create_index(
        "ix_tournament_round_pairings_messages_edit_disabled_at",
        "tournament_round_pairings_messages",
        ["edit_disabled_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tournament_round_pairings_messages_edit_disabled_at",
        table_name="tournament_round_pairings_messages",
    )
    op.drop_index(
        "ix_tournament_round_pairings_messages_tournament_id",
        table_name="tournament_round_pairings_messages",
    )
    op.drop_table("tournament_round_pairings_messages")
