"""add club announcement settings

Revision ID: 11cdd73fac96
Revises: 4953faa801dd
Create Date: 2026-09-04
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "11cdd73fac96"
down_revision: Union[str, Sequence[str], None] = "4953faa801dd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tournament_creation_plans", sa.Column("announcement_chat_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "tournament_creation_plans",
        sa.Column("announcement_chat_label", sa.String(length=255), server_default="не отправлять", nullable=False),
    )
    op.create_table(
        "club_announcement_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("club_name", sa.String(length=64), nullable=False),
        sa.Column("destination", sa.String(length=16), server_default="none", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("club_name"),
    )
    op.create_index("ix_club_announcement_settings_id", "club_announcement_settings", ["id"])
    op.create_index("ix_club_announcement_settings_club_name", "club_announcement_settings", ["club_name"])


def downgrade() -> None:
    op.drop_index("ix_club_announcement_settings_club_name", table_name="club_announcement_settings")
    op.drop_index("ix_club_announcement_settings_id", table_name="club_announcement_settings")
    op.drop_table("club_announcement_settings")
    op.drop_column("tournament_creation_plans", "announcement_chat_label")
    op.drop_column("tournament_creation_plans", "announcement_chat_id")
