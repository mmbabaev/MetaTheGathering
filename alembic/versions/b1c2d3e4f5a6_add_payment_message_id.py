"""add payment tg_chat_id and tg_message_id

Revision ID: b1c2d3e4f5a6
Revises: a6b7c8d9e0f1
Create Date: 2026-04-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("tg_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("payments", sa.Column("tg_message_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "tg_message_id")
    op.drop_column("payments", "tg_chat_id")
