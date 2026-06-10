"""add user status_by_pairings setting

Revision ID: 40f49c4eba55
Revises: 9fc68f844468
Create Date: 2026-06-10 10:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "40f49c4eba55"
down_revision: Union[str, Sequence[str], None] = "9fc68f844468"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("status_by_pairings", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "status_by_pairings")
