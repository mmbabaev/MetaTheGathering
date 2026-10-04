"""add local Endstep tournament result snapshots

Revision ID: 59c54037a9d8
Revises: e528f8f092f9
Create Date: 2026-10-04
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "59c54037a9d8"
down_revision: Union[str, Sequence[str], None] = "e528f8f092f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "endstep_tournaments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_key", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("format_name", sa.String(length=64), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_key"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_endstep_tournaments_id", "endstep_tournaments", ["id"])
    op.create_index("ix_endstep_tournaments_external_key", "endstep_tournaments", ["external_key"])
    op.create_index("ix_endstep_tournaments_slug", "endstep_tournaments", ["slug"])

    op.create_table(
        "scryfall_cards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=True),
        sa.Column("scryfall_id", sa.String(length=64), nullable=True),
        sa.Column("image_uri", sa.String(length=1024), nullable=True),
        sa.Column("image_uri_back", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name"),
        sa.UniqueConstraint("scryfall_id"),
    )
    op.create_index("ix_scryfall_cards_id", "scryfall_cards", ["id"])
    op.create_index("ix_scryfall_cards_normalized_name", "scryfall_cards", ["normalized_name"])

    op.create_table(
        "endstep_standings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("place", sa.Integer(), nullable=False),
        sa.Column("player_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("match_points", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("losses", sa.Integer(), nullable=False),
        sa.Column("draws", sa.Integer(), nullable=False),
        sa.Column("omw_percent", sa.Float(), nullable=True),
        sa.Column("gw_percent", sa.Float(), nullable=True),
        sa.Column("ogw_percent", sa.Float(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["endstep_tournaments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tournament_id", "player_name", name="uq_endstep_standing_player"),
    )
    op.create_index("ix_endstep_standings_id", "endstep_standings", ["id"])
    op.create_index("ix_endstep_standings_tournament_id", "endstep_standings", ["tournament_id"])
    op.create_index("ix_endstep_standings_user_id", "endstep_standings", ["user_id"])

    op.create_table(
        "endstep_pairings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("table_number", sa.Integer(), nullable=True),
        sa.Column("player1", sa.String(length=255), nullable=True),
        sa.Column("player2", sa.String(length=255), nullable=True),
        sa.Column("games", sa.String(length=32), nullable=True),
        sa.Column("result", sa.String(length=64), nullable=True),
        sa.Column("winner", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["endstep_tournaments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_endstep_pairings_id", "endstep_pairings", ["id"])
    op.create_index("ix_endstep_pairings_tournament_id", "endstep_pairings", ["tournament_id"])

    op.create_table(
        "endstep_deck_cards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("place", sa.Integer(), nullable=True),
        sa.Column("player_name", sa.String(length=255), nullable=False),
        sa.Column("section", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("card_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("scryfall_card_id", sa.Integer(), nullable=True),
        sa.Column("scryfall_id", sa.String(length=64), nullable=True),
        sa.Column("image_uri", sa.String(length=1024), nullable=True),
        sa.Column("image_uri_back", sa.String(length=1024), nullable=True),
        sa.ForeignKeyConstraint(["scryfall_card_id"], ["scryfall_cards.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tournament_id"], ["endstep_tournaments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_endstep_deck_cards_id", "endstep_deck_cards", ["id"])
    op.create_index("ix_endstep_deck_cards_tournament_id", "endstep_deck_cards", ["tournament_id"])
    op.create_index("ix_endstep_deck_cards_normalized_name", "endstep_deck_cards", ["normalized_name"])
    op.create_index("ix_endstep_deck_cards_scryfall_card_id", "endstep_deck_cards", ["scryfall_card_id"])
    op.create_index(
        "ix_endstep_deck_player_section",
        "endstep_deck_cards",
        ["tournament_id", "player_name", "section"],
    )


def downgrade() -> None:
    op.drop_index("ix_endstep_deck_player_section", table_name="endstep_deck_cards")
    op.drop_index("ix_endstep_deck_cards_scryfall_card_id", table_name="endstep_deck_cards")
    op.drop_index("ix_endstep_deck_cards_normalized_name", table_name="endstep_deck_cards")
    op.drop_index("ix_endstep_deck_cards_tournament_id", table_name="endstep_deck_cards")
    op.drop_index("ix_endstep_deck_cards_id", table_name="endstep_deck_cards")
    op.drop_table("endstep_deck_cards")
    op.drop_index("ix_endstep_pairings_tournament_id", table_name="endstep_pairings")
    op.drop_index("ix_endstep_pairings_id", table_name="endstep_pairings")
    op.drop_table("endstep_pairings")
    op.drop_index("ix_endstep_standings_user_id", table_name="endstep_standings")
    op.drop_index("ix_endstep_standings_tournament_id", table_name="endstep_standings")
    op.drop_index("ix_endstep_standings_id", table_name="endstep_standings")
    op.drop_table("endstep_standings")
    op.drop_index("ix_scryfall_cards_normalized_name", table_name="scryfall_cards")
    op.drop_index("ix_scryfall_cards_id", table_name="scryfall_cards")
    op.drop_table("scryfall_cards")
    op.drop_index("ix_endstep_tournaments_slug", table_name="endstep_tournaments")
    op.drop_index("ix_endstep_tournaments_external_key", table_name="endstep_tournaments")
    op.drop_index("ix_endstep_tournaments_id", table_name="endstep_tournaments")
    op.drop_table("endstep_tournaments")
