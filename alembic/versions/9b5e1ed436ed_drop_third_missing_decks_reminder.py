"""drop third-day missing decks reminder

Revision ID: 9b5e1ed436ed
Revises: 5e2bd7e0283f
Create Date: 2026-08-17
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "9b5e1ed436ed"
down_revision: Union[str, Sequence[str], None] = "5e2bd7e0283f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("tournaments", "missing_decks_reminder_3d_sent_at")


def downgrade() -> None:
    op.add_column("tournaments", sa.Column("missing_decks_reminder_3d_sent_at", sa.DateTime(), nullable=True))
