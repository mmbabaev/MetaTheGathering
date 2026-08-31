"""track participants observed in AetherHub imports

Revision ID: 0fc3b8429cb0
Revises: a62db8f5ffdd
Create Date: 2026-09-01
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0fc3b8429cb0"
down_revision: Union[str, Sequence[str], None] = "a62db8f5ffdd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable and deliberately not backfilled: imports populate it from observed rosters.
    op.add_column("participants", sa.Column("aetherhub_seen_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("participants", "aetherhub_seen_at")
