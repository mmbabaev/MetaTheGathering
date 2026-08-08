"""add unclosed tournament reminder timestamps

Revision ID: f91459d45e99
Revises: aa8d0dcf98b8
Create Date: 2026-08-08
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f91459d45e99"
down_revision: Union[str, Sequence[str], None] = "aa8d0dcf98b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tournaments", sa.Column("unclosed_reminder_3d_sent_at", sa.DateTime(), nullable=True))
    op.add_column("tournaments", sa.Column("unclosed_reminder_7d_sent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("tournaments", "unclosed_reminder_7d_sent_at")
    op.drop_column("tournaments", "unclosed_reminder_3d_sent_at")
