"""complete achievement hardening

Revision ID: 2a5b53ae1edf
Revises: f91459d45e99
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "2a5b53ae1edf"
down_revision: Union[str, Sequence[str], None] = "f91459d45e99"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("notify_achievements", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("achievement_report_deliveries", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column(
        "achievement_report_deliveries",
        sa.Column("payload_type", sa.String(length=32), nullable=False, server_default="achievement_report"),
    )
    op.add_column(
        "achievement_report_deliveries",
        sa.Column("payload_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("achievement_report_deliveries", sa.Column("idempotency_key", sa.String(length=160), nullable=True))
    op.create_foreign_key(
        "fk_achievement_delivery_user",
        "achievement_report_deliveries",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_achievement_report_deliveries_user_id", "achievement_report_deliveries", ["user_id"])
    op.create_unique_constraint(
        "uq_achievement_report_delivery_idempotency",
        "achievement_report_deliveries",
        ["idempotency_key"],
    )
    op.create_check_constraint(
        "ck_achievement_player_delivery_targeted",
        "achievement_report_deliveries",
        "recipient_type != 'player' OR (user_id IS NOT NULL AND chat_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_achievement_delivery_payload_version",
        "achievement_report_deliveries",
        "payload_version > 0",
    )

    op.create_table(
        "achievement_progress_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False, server_default="calculated"),
        sa.Column("tournament_id", sa.Integer(), nullable=True),
        sa.Column("processing_run_id", sa.Integer(), nullable=True),
        sa.Column("before_value", sa.Integer(), nullable=False),
        sa.Column("after_value", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.String(length=512), nullable=True),
        sa.Column("requirements_json", sa.Text(), nullable=False),
        sa.Column("source_tournament_ids_json", sa.Text(), nullable=False),
        sa.Column("match_ids_json", sa.Text(), nullable=False),
        sa.Column("stats_snapshot_json", sa.Text(), nullable=False),
        sa.Column("ruleset_version", sa.Integer(), nullable=False),
        sa.Column("stats_version", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["processing_run_id"], ["achievement_processing_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_achievement_progress_event_idempotency"),
    )
    op.create_index("ix_achievement_progress_events_id", "achievement_progress_events", ["id"])
    op.create_index("ix_achievement_progress_events_user_id", "achievement_progress_events", ["user_id"])
    op.create_index("ix_achievement_progress_events_code", "achievement_progress_events", ["code"])
    op.create_index("ix_achievement_progress_events_tournament_id", "achievement_progress_events", ["tournament_id"])
    op.create_index(
        "ix_achievement_progress_events_processing_run_id",
        "achievement_progress_events",
        ["processing_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_achievement_progress_events_processing_run_id", table_name="achievement_progress_events")
    op.drop_index("ix_achievement_progress_events_tournament_id", table_name="achievement_progress_events")
    op.drop_index("ix_achievement_progress_events_code", table_name="achievement_progress_events")
    op.drop_index("ix_achievement_progress_events_user_id", table_name="achievement_progress_events")
    op.drop_index("ix_achievement_progress_events_id", table_name="achievement_progress_events")
    op.drop_table("achievement_progress_events")

    op.drop_constraint("uq_achievement_report_delivery_idempotency", "achievement_report_deliveries", type_="unique")
    op.drop_constraint("ck_achievement_delivery_payload_version", "achievement_report_deliveries", type_="check")
    op.drop_constraint("ck_achievement_player_delivery_targeted", "achievement_report_deliveries", type_="check")
    op.drop_index("ix_achievement_report_deliveries_user_id", table_name="achievement_report_deliveries")
    op.drop_constraint("fk_achievement_delivery_user", "achievement_report_deliveries", type_="foreignkey")
    op.drop_column("achievement_report_deliveries", "idempotency_key")
    op.drop_column("achievement_report_deliveries", "payload_version")
    op.drop_column("achievement_report_deliveries", "payload_type")
    op.drop_column("achievement_report_deliveries", "user_id")
    op.drop_column("users", "notify_achievements")
