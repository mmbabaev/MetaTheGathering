"""add achievement processing runs

Revision ID: aa8d0dcf98b8
Revises: cec6ea90e42a
Create Date: 2026-08-08
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "aa8d0dcf98b8"
down_revision: Union[str, Sequence[str], None] = "cec6ea90e42a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "achievement_processing_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("engine_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rules_total", sa.Integer(), nullable=False),
        sa.Column("rules_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("granted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_changes_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rule_errors_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_achievement_processing_runs_id", "achievement_processing_runs", ["id"])
    op.create_index(
        "ix_achievement_processing_runs_tournament_id",
        "achievement_processing_runs",
        ["tournament_id"],
    )
    op.create_index("ix_achievement_processing_runs_status", "achievement_processing_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_achievement_processing_runs_status", table_name="achievement_processing_runs")
    op.drop_index("ix_achievement_processing_runs_tournament_id", table_name="achievement_processing_runs")
    op.drop_index("ix_achievement_processing_runs_id", table_name="achievement_processing_runs")
    op.drop_table("achievement_processing_runs")
