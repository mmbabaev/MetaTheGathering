"""add tournament closed-by audit field

Revision ID: 1ab9c3d7dda1
Revises: 36595f965e2c
Create Date: 2026-08-29
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "1ab9c3d7dda1"
down_revision: Union[str, Sequence[str], None] = "36595f965e2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tournaments", sa.Column("closed_by_tg_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("tournaments", "closed_by_tg_id")
