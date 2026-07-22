"""add poll_regulars

Revision ID: 7f446c079123
Revises: b0d6a607fe5d
Create Date: 2026-07-22

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "7f446c079123"
down_revision: Union[str, Sequence[str], None] = "b0d6a607fe5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "poll_regulars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("chat_id", "user_id", name="uq_poll_regular_unique"),
    )
    op.create_index("ix_poll_regulars_chat_id", "poll_regulars", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_poll_regulars_chat_id", table_name="poll_regulars")
    op.drop_table("poll_regulars")
