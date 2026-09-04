"""add online round results

Revision ID: 71797c25e8da
Revises: 11cdd73fac96
Create Date: 2026-09-04
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "71797c25e8da"
down_revision: Union[str, Sequence[str], None] = "11cdd73fac96"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tournaments",
        sa.Column("show_round_pairings", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "round_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("table_number", sa.Integer(), nullable=True),
        sa.Column("pairing_key", sa.String(length=64), nullable=False),
        sa.Column("player1_name", sa.String(length=255), nullable=False),
        sa.Column("player2_name", sa.String(length=255), nullable=True),
        sa.Column("player1_user_id", sa.Integer(), nullable=True),
        sa.Column("player2_user_id", sa.Integer(), nullable=True),
        sa.Column("player1_wins", sa.Integer(), nullable=True),
        sa.Column("player2_wins", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="unreported", nullable=False),
        sa.Column("proposed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("player1_wins IS NULL OR player1_wins BETWEEN 0 AND 2", name="ck_round_match_p1_wins"),
        sa.CheckConstraint("player2_wins IS NULL OR player2_wins BETWEEN 0 AND 2", name="ck_round_match_p2_wins"),
        sa.CheckConstraint(
            "player1_wins IS NULL OR player2_wins IS NULL OR player1_wins <> 2 OR player2_wins <> 2",
            name="ck_round_match_not_2_2",
        ),
        sa.ForeignKeyConstraint(["player1_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["player2_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proposed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["confirmed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tournament_id", "round_number", "pairing_key", name="uq_round_match_pair"),
    )
    op.create_index("ix_round_matches_id", "round_matches", ["id"])
    op.create_index("ix_round_matches_tournament_id", "round_matches", ["tournament_id"])
    op.create_table(
        "round_match_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_tg_id", sa.BigInteger(), nullable=True),
        sa.Column("player1_wins", sa.Integer(), nullable=True),
        sa.Column("player2_wins", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["match_id"], ["round_matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_round_match_events_id", "round_match_events", ["id"])
    op.create_index("ix_round_match_events_match_id", "round_match_events", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_round_match_events_match_id", table_name="round_match_events")
    op.drop_index("ix_round_match_events_id", table_name="round_match_events")
    op.drop_table("round_match_events")
    op.drop_index("ix_round_matches_tournament_id", table_name="round_matches")
    op.drop_index("ix_round_matches_id", table_name="round_matches")
    op.drop_table("round_matches")
    op.drop_column("tournaments", "show_round_pairings")
