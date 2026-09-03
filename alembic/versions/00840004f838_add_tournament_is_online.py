"""add tournament online marker

Revision ID: 00840004f838
Revises: 0fc3b8429cb0
Create Date: 2026-09-04
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "00840004f838"
down_revision: Union[str, Sequence[str], None] = "0fc3b8429cb0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing tournaments are physical; the database default also makes omitted values offline.
    op.add_column(
        "tournaments",
        sa.Column("is_online", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("tournaments", "is_online")
