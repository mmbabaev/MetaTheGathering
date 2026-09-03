"""add tournament creation plans

Revision ID: 4953faa801dd
Revises: 00840004f838
Create Date: 2026-09-04
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "4953faa801dd"
down_revision: Union[str, Sequence[str], None] = "00840004f838"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tournament_creation_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("club_name", sa.String(length=64), nullable=False),
        sa.Column("created_by_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("announce_at", sa.DateTime(), nullable=False),
        sa.Column("event_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=True),
        sa.Column("announcement_sent_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tournament_id"),
    )
    op.create_index("ix_tournament_creation_plans_id", "tournament_creation_plans", ["id"])
    op.create_index("ix_tournament_creation_plans_club_name", "tournament_creation_plans", ["club_name"])
    op.create_index(
        "ix_tournament_creation_plans_created_by_tg_id",
        "tournament_creation_plans",
        ["created_by_tg_id"],
    )
    op.create_index("ix_tournament_creation_plans_announce_at", "tournament_creation_plans", ["announce_at"])
    op.create_index("ix_tournament_creation_plans_status", "tournament_creation_plans", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tournament_creation_plans_status", table_name="tournament_creation_plans")
    op.drop_index("ix_tournament_creation_plans_announce_at", table_name="tournament_creation_plans")
    op.drop_index("ix_tournament_creation_plans_created_by_tg_id", table_name="tournament_creation_plans")
    op.drop_index("ix_tournament_creation_plans_club_name", table_name="tournament_creation_plans")
    op.drop_index("ix_tournament_creation_plans_id", table_name="tournament_creation_plans")
    op.drop_table("tournament_creation_plans")
