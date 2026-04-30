"""web_link_requests

Revision ID: a2b3c4d5e6f7
Revises: 141bc09d4548
Create Date: 2026-04-30 13:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "141bc09d4548"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "web_link_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("web_user_id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=6), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tg_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["web_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_web_link_requests_id"), "web_link_requests", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_web_link_requests_id"), table_name="web_link_requests")
    op.drop_table("web_link_requests")
