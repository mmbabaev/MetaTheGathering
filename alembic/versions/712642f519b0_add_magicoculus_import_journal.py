"""add Magic Oculus import journal

Revision ID: 712642f519b0
Revises: 2c906a8d5c01
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "712642f519b0"
down_revision: Union[str, Sequence[str], None] = "2c906a8d5c01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "magicoculus_imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("aetherhub_url", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("magicoculus_tournament_id", sa.Integer(), nullable=True),
        sa.Column("warnings_json", sa.String(), nullable=True),
        sa.Column("error_json", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("aetherhub_url"),
        sa.UniqueConstraint("magicoculus_tournament_id"),
        sa.UniqueConstraint("tournament_id"),
    )
    op.create_index("ix_magicoculus_imports_id", "magicoculus_imports", ["id"])
    op.create_index("ix_magicoculus_imports_tournament_id", "magicoculus_imports", ["tournament_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_magicoculus_imports_tournament_id", table_name="magicoculus_imports")
    op.drop_index("ix_magicoculus_imports_id", table_name="magicoculus_imports")
    op.drop_table("magicoculus_imports")
