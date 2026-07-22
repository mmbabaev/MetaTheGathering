"""add user is_poll_organizer + notify_poll

Revision ID: 94b5f49c6961
Revises: 431364012714
Create Date: 2026-07-22

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "94b5f49c6961"
down_revision: Union[str, Sequence[str], None] = "431364012714"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_poll_organizer", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "users",
        sa.Column("notify_poll", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("users", "notify_poll")
    op.drop_column("users", "is_poll_organizer")
