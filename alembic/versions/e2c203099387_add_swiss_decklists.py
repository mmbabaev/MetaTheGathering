"""add internal Swiss decklists and reminder gating

Revision ID: e2c203099387
Revises: e2c9d12d05ed
Create Date: 2026-09-18
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e2c203099387"
down_revision: Union[str, Sequence[str], None] = "e2c9d12d05ed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tournaments", sa.Column("created_by_tg_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_tournaments_created_by_tg_id", "tournaments", ["created_by_tg_id"], unique=False)
    op.add_column(
        "tournaments",
        sa.Column("decklist_reminders_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "participants",
        sa.Column("swiss_requirements_reminder_sent_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "participant_decklists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("participant_id", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("participant_id"),
    )
    op.create_index(
        "ix_participant_decklists_participant_id",
        "participant_decklists",
        ["participant_id"],
        unique=True,
    )

    # Manual creation plans already record their creator.  Preserve that
    # ownership for linked legacy tournaments without opting them into DMs.
    op.execute(
        sa.text(
            """
            UPDATE tournaments
            SET created_by_tg_id = (
                SELECT tournament_creation_plans.created_by_tg_id
                FROM tournament_creation_plans
                WHERE tournament_creation_plans.tournament_id = tournaments.id
            )
            WHERE EXISTS (
                SELECT 1 FROM tournament_creation_plans
                WHERE tournament_creation_plans.tournament_id = tournaments.id
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_participant_decklists_participant_id", table_name="participant_decklists")
    op.drop_table("participant_decklists")
    op.drop_column("participants", "swiss_requirements_reminder_sent_at")
    op.drop_column("tournaments", "decklist_reminders_enabled")
    op.drop_index("ix_tournaments_created_by_tg_id", table_name="tournaments")
    op.drop_column("tournaments", "created_by_tg_id")
