"""add poll_notifications

Revision ID: b0d6a607fe5d
Revises: 94b5f49c6961
Create Date: 2026-07-22

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b0d6a607fe5d"
down_revision: Union[str, Sequence[str], None] = "94b5f49c6961"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "poll_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "poll_id",
            sa.Integer(),
            sa.ForeignKey("tournament_polls.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("poll_id", "tg_user_id", name="uq_poll_notification_unique"),
    )
    op.create_index("ix_poll_notifications_poll_id", "poll_notifications", ["poll_id"])


def downgrade() -> None:
    op.drop_index("ix_poll_notifications_poll_id", table_name="poll_notifications")
    op.drop_table("poll_notifications")
