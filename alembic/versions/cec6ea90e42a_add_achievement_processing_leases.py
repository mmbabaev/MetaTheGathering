"""add achievement processing leases

Revision ID: cec6ea90e42a
Revises: 82b0e3af200f
Create Date: 2026-08-08
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "cec6ea90e42a"
down_revision: Union[str, Sequence[str], None] = "82b0e3af200f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "achievement_processing_leases",
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=32), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tournament_id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index(
        "ix_achievement_processing_leases_locked_until",
        "achievement_processing_leases",
        ["locked_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_achievement_processing_leases_locked_until", table_name="achievement_processing_leases")
    op.drop_table("achievement_processing_leases")
