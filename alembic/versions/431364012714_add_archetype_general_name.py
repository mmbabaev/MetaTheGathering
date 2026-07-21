"""add archetype.general_name

Revision ID: 431364012714
Revises: 3067ed27a905
Create Date: 2026-07-21

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "431364012714"
down_revision: Union[str, Sequence[str], None] = "3067ed27a905"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "archetypes",
        sa.Column("general_name", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_archetypes_general_name", "archetypes", ["general_name"])


def downgrade() -> None:
    op.drop_index("ix_archetypes_general_name", table_name="archetypes")
    op.drop_column("archetypes", "general_name")
