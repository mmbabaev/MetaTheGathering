"""track AetherHub not-found owner notification

Revision ID: 36595f965e2c
Revises: a6fbdbee0220
Create Date: 2026-08-29
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "36595f965e2c"
down_revision: Union[str, Sequence[str], None] = "a6fbdbee0220"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tournaments", sa.Column("aetherhub_not_found_notified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("tournaments", "aetherhub_not_found_notified_at")
