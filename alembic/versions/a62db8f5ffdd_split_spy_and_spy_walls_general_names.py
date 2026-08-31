"""split Spy and Spy Walls general names

Revision ID: a62db8f5ffdd
Revises: 1ab9c3d7dda1
Create Date: 2026-09-01
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a62db8f5ffdd"
down_revision: Union[str, Sequence[str], None] = "1ab9c3d7dda1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Исправляем только подтверждённые варианты старого кэша. Исходные name и ссылки
    # участников не меняются: Spy/Spy Combo отделяются от Spy Walls/Walls combo.
    op.execute(
        sa.text(
            "UPDATE archetypes SET general_name = CASE lower(trim(name)) "
            "WHEN 'spy' THEN 'Spy' "
            "WHEN 'spy combo' THEN 'Spy' "
            "WHEN 'spy walls' THEN 'Spy Walls' "
            "WHEN 'walls combo' THEN 'Spy Walls' "
            "ELSE general_name END "
            "WHERE lower(trim(name)) IN ('spy', 'spy combo', 'spy walls', 'walls combo')"
        )
    )


def downgrade() -> None:
    # Classification repairs are intentionally data-preserving on downgrade.
    pass
