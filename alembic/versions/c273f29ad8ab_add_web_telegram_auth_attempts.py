"""add short-lived Telegram web login attempts

Revision ID: c273f29ad8ab
Revises: 59c54037a9d8
Create Date: 2026-10-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c273f29ad8ab"
down_revision: Union[str, Sequence[str], None] = "59c54037a9d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "web_telegram_auth_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_web_telegram_auth_attempts_id", "web_telegram_auth_attempts", ["id"])
    op.create_index(
        "ix_web_telegram_auth_attempts_token_hash",
        "web_telegram_auth_attempts",
        ["token_hash"],
        unique=True,
    )
    op.create_index("ix_web_telegram_auth_attempts_user_id", "web_telegram_auth_attempts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_web_telegram_auth_attempts_user_id", table_name="web_telegram_auth_attempts")
    op.drop_index("ix_web_telegram_auth_attempts_token_hash", table_name="web_telegram_auth_attempts")
    op.drop_index("ix_web_telegram_auth_attempts_id", table_name="web_telegram_auth_attempts")
    op.drop_table("web_telegram_auth_attempts")
