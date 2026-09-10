"""add durable Ranked activation evidence to participants

Revision ID: 6b75338db854
Revises: 7167a65fad51
Create Date: 2026-09-10
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "6b75338db854"
down_revision: Union[str, Sequence[str], None] = "7167a65fad51"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("participants", sa.Column("ranked_activated_at", sa.DateTime(), nullable=True))
    op.add_column("participants", sa.Column("ranked_activation_source", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("participants", "ranked_activation_source")
    op.drop_column("participants", "ranked_activated_at")
