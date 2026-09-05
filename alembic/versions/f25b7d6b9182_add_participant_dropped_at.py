"""track Swiss tournament drops

Revision ID: f25b7d6b9182
Revises: 330c09696d85
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f25b7d6b9182"
down_revision: Union[str, Sequence[str], None] = "330c09696d85"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("participants", sa.Column("dropped_at", sa.DateTime(), nullable=True))
    op.create_index("ix_participants_dropped_at", "participants", ["dropped_at"])


def downgrade() -> None:
    op.drop_index("ix_participants_dropped_at", table_name="participants")
    op.drop_column("participants", "dropped_at")
