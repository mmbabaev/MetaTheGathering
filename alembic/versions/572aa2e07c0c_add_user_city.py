"""add user city

Revision ID: 572aa2e07c0c
Revises: f25b7d6b9182
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "572aa2e07c0c"
down_revision: Union[str, Sequence[str], None] = "f25b7d6b9182"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("city", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "city")
