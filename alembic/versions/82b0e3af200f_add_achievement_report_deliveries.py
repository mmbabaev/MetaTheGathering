"""add achievement report deliveries

Revision ID: 82b0e3af200f
Revises: a058f39d9db8
Create Date: 2026-08-08
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "82b0e3af200f"
down_revision: Union[str, Sequence[str], None] = "a058f39d9db8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "achievement_report_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.String(length=32), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("recipient_type", sa.String(length=16), nullable=False, server_default="owner"),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("message_index", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "message_index", name="uq_achievement_report_delivery_message"),
    )
    op.create_index(
        "ix_achievement_report_deliveries_id", "achievement_report_deliveries", ["id"]
    )
    op.create_index(
        "ix_achievement_report_deliveries_report_id",
        "achievement_report_deliveries",
        ["report_id"],
    )
    op.create_index(
        "ix_achievement_report_deliveries_tournament_id",
        "achievement_report_deliveries",
        ["tournament_id"],
    )
    op.create_index(
        "ix_achievement_report_deliveries_status",
        "achievement_report_deliveries",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_achievement_report_deliveries_status", table_name="achievement_report_deliveries")
    op.drop_index("ix_achievement_report_deliveries_tournament_id", table_name="achievement_report_deliveries")
    op.drop_index("ix_achievement_report_deliveries_report_id", table_name="achievement_report_deliveries")
    op.drop_index("ix_achievement_report_deliveries_id", table_name="achievement_report_deliveries")
    op.drop_table("achievement_report_deliveries")
