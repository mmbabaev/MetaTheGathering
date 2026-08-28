"""add cellar notification preference

Revision ID: 5132b26f0434
Revises: a8bd90c89a94
Create Date: 2026-08-24
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "5132b26f0434"
down_revision: Union[str, Sequence[str], None] = "a8bd90c89a94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("notify_cellar_reservations", sa.Boolean(), server_default="true", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "notify_cellar_reservations")
