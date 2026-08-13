"""split spy and walls macro families

Revision ID: 4b2a49905e82
Revises: f24df28a306e
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "4b2a49905e82"
down_revision: Union[str, Sequence[str], None] = "f24df28a306e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PR #225 уже записал эти два подтверждённых Spy-варианта как Walls.
    # Исправляем только macro-кэш; исходные name/general_name и participant links не меняем.
    op.execute(
        sa.text(
            "UPDATE archetypes SET macro_name = 'Spy' "
            "WHERE lower(name) IN ('spy combo', 'spy walls')"
        )
    )


def downgrade() -> None:
    # Classification repairs are intentionally data-preserving on downgrade.
    pass
