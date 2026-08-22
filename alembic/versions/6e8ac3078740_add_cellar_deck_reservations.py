"""add cellar deck reservations

Revision ID: 6e8ac3078740
Revises: a6fbdbee0220
Create Date: 2026-08-22
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "6e8ac3078740"
down_revision: Union[str, Sequence[str], None] = "a6fbdbee0220"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cellar_decks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("archetype_name", sa.String(length=255), nullable=False),
        sa.Column("decklist_url", sa.String(length=512), nullable=True),
        sa.Column("notes", sa.String(length=512), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cellar_decks_active", "cellar_decks", ["active"])
    op.create_index("ix_cellar_decks_source_key", "cellar_decks", ["source_key"], unique=True)

    op.create_table(
        "cellar_coordinator_reminders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("recipient_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_date", "recipient_tg_id", name="uq_cellar_coordinator_event_recipient"),
    )
    op.create_index(
        "ix_cellar_coordinator_reminders_event_date",
        "cellar_coordinator_reminders",
        ["event_date"],
    )

    op.create_table(
        "cellar_deck_reservations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deck_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=True),
        sa.Column("participant_id", sa.Integer(), nullable=True),
        sa.Column("applied_archetype_id", sa.Integer(), nullable=True),
        sa.Column("previous_archetype_id", sa.Integer(), nullable=True),
        sa.Column("previous_deck_added_by_tg_id", sa.BigInteger(), nullable=True),
        sa.Column("previous_deck_deferred", sa.Boolean(), nullable=True),
        sa.Column("participant_created", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("group_announced_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["applied_archetype_id"], ["archetypes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deck_id"], ["cellar_decks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["previous_archetype_id"], ["archetypes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cellar_deck_reservations_cancelled_at",
        "cellar_deck_reservations",
        ["cancelled_at"],
    )
    op.create_index("ix_cellar_deck_reservations_deck_id", "cellar_deck_reservations", ["deck_id"])
    op.create_index("ix_cellar_deck_reservations_event_date", "cellar_deck_reservations", ["event_date"])
    op.create_index("ix_cellar_deck_reservations_tournament_id", "cellar_deck_reservations", ["tournament_id"])
    op.create_index("ix_cellar_deck_reservations_user_id", "cellar_deck_reservations", ["user_id"])
    op.create_index(
        "uq_active_cellar_deck_event",
        "cellar_deck_reservations",
        ["deck_id", "event_date"],
        unique=True,
        postgresql_where=sa.text("cancelled_at IS NULL"),
        sqlite_where=sa.text("cancelled_at IS NULL"),
    )
    op.create_index(
        "uq_active_cellar_user_event",
        "cellar_deck_reservations",
        ["user_id", "event_date"],
        unique=True,
        postgresql_where=sa.text("cancelled_at IS NULL"),
        sqlite_where=sa.text("cancelled_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_active_cellar_user_event", table_name="cellar_deck_reservations")
    op.drop_index("uq_active_cellar_deck_event", table_name="cellar_deck_reservations")
    op.drop_index("ix_cellar_deck_reservations_user_id", table_name="cellar_deck_reservations")
    op.drop_index("ix_cellar_deck_reservations_tournament_id", table_name="cellar_deck_reservations")
    op.drop_index("ix_cellar_deck_reservations_event_date", table_name="cellar_deck_reservations")
    op.drop_index("ix_cellar_deck_reservations_deck_id", table_name="cellar_deck_reservations")
    op.drop_index("ix_cellar_deck_reservations_cancelled_at", table_name="cellar_deck_reservations")
    op.drop_table("cellar_deck_reservations")
    op.drop_index("ix_cellar_coordinator_reminders_event_date", table_name="cellar_coordinator_reminders")
    op.drop_table("cellar_coordinator_reminders")
    op.drop_index("ix_cellar_decks_source_key", table_name="cellar_decks")
    op.drop_index("ix_cellar_decks_active", table_name="cellar_decks")
    op.drop_table("cellar_decks")
