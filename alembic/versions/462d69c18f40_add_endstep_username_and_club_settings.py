"""add Endstep username and club settings

Revision ID: 462d69c18f40
Revises: 71797c25e8da
Create Date: 2026-09-04
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "462d69c18f40"
down_revision: Union[str, Sequence[str], None] = "71797c25e8da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("endstep_username", sa.String(length=255), nullable=True))
    op.create_index("ix_users_endstep_username", "users", ["endstep_username"], unique=True)
    op.create_table(
        "club_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("club_name", sa.String(length=64), nullable=False),
        sa.Column("publish_pairings", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_club_settings_id", "club_settings", ["id"], unique=False)
    op.create_index("ix_club_settings_club_name", "club_settings", ["club_name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_club_settings_club_name", table_name="club_settings")
    op.drop_index("ix_club_settings_id", table_name="club_settings")
    op.drop_table("club_settings")
    op.drop_index("ix_users_endstep_username", table_name="users")
    op.drop_column("users", "endstep_username")
