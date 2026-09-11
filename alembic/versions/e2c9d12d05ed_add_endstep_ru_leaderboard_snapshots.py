"""add persisted Endstep RU leaderboard snapshots

Revision ID: e2c9d12d05ed
Revises: 6b75338db854
Create Date: 2026-09-11
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e2c9d12d05ed"
down_revision: Union[str, Sequence[str], None] = "6b75338db854"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "endstep_ru_leaderboard_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("rows_json", sa.Text(), nullable=False),
        sa.Column("missing_usernames_json", sa.Text(), nullable=False),
        sa.Column("ambiguous_usernames_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_endstep_ru_leaderboard_snapshots_generated_at",
        "endstep_ru_leaderboard_snapshots",
        ["generated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_endstep_ru_leaderboard_snapshots_generated_at",
        table_name="endstep_ru_leaderboard_snapshots",
    )
    op.drop_table("endstep_ru_leaderboard_snapshots")
