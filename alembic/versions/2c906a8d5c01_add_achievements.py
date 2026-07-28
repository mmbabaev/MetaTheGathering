"""add user_achievements and user_achievement_progress

Revision ID: 2c906a8d5c01
Revises: 7c178567f22c
Create Date: 2026-07-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2c906a8d5c01"
down_revision: Union[str, Sequence[str], None] = "7c178567f22c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_achievements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("tournament_id", sa.Integer(), nullable=True),
        sa.Column("progress_value", sa.Integer(), nullable=True),
        sa.Column("evidence", sa.String(length=512), nullable=True),
        sa.Column("awarded_at", sa.DateTime(), nullable=False),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "code", "level", name="uq_user_achievement"),
    )
    op.create_index("ix_user_achievements_id", "user_achievements", ["id"])
    op.create_index("ix_user_achievements_user_id", "user_achievements", ["user_id"])

    op.create_table(
        "user_achievement_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tournament_id", sa.Integer(), nullable=True),
        sa.Column("evidence", sa.String(length=512), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "code", name="uq_user_achievement_progress"),
    )
    op.create_index("ix_user_achievement_progress_id", "user_achievement_progress", ["id"])
    op.create_index("ix_user_achievement_progress_user_id", "user_achievement_progress", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_achievement_progress_user_id", table_name="user_achievement_progress")
    op.drop_index("ix_user_achievement_progress_id", table_name="user_achievement_progress")
    op.drop_table("user_achievement_progress")
    op.drop_index("ix_user_achievements_user_id", table_name="user_achievements")
    op.drop_index("ix_user_achievements_id", table_name="user_achievements")
    op.drop_table("user_achievements")
