"""add Endstep draft tournaments and organizer role

Revision ID: e5b393c08316
Revises: e2c203099387
Create Date: 2026-09-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5b393c08316"
down_revision: Union[str, Sequence[str], None] = "e2c203099387"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_tournament_organizer", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "tournaments",
        sa.Column("is_draft", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index("ix_tournaments_is_draft", "tournaments", ["is_draft"], unique=False)
    op.add_column("tournaments", sa.Column("draft_seating_generated_at", sa.DateTime(), nullable=True))
    op.add_column("participants", sa.Column("draft_seat", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE users SET is_tournament_organizer = true "
            "WHERE lower(username) IN ('playasdevil', '@playasdevil')"
        )
    )


def downgrade() -> None:
    op.drop_column("participants", "draft_seat")
    op.drop_column("tournaments", "draft_seating_generated_at")
    op.drop_index("ix_tournaments_is_draft", table_name="tournaments")
    op.drop_column("tournaments", "is_draft")
    op.drop_column("users", "is_tournament_organizer")
