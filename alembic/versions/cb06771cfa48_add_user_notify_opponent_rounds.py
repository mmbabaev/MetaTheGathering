"""add user.notify_opponent_rounds

Revision ID: cb06771cfa48
Revises: aac3d24c4e09
Create Date: 2026-06-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "cb06771cfa48"
down_revision: Union[str, Sequence[str], None] = "aac3d24c4e09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("notify_opponent_rounds", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("users", "notify_opponent_rounds")
