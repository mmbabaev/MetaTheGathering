"""add archetype macro name and normalize gardens

Revision ID: a058f39d9db8
Revises: e7b4e1fa452a
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a058f39d9db8"
down_revision: Union[str, None] = "e7b4e1fa452a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("archetypes", sa.Column("macro_name", sa.String(length=255), nullable=True))
    op.create_index("ix_archetypes_macro_name", "archetypes", ["macro_name"])

    # Исправляем уже накопленный кэш. Gardens в Pauper не имеет цветовых вариантов.
    op.execute(
        sa.text(
            "UPDATE archetypes SET general_name = 'BG Gardens' "
            "WHERE lower(name) LIKE '%gardens%'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE archetypes SET macro_name = CASE "
            "WHEN lower(general_name) LIKE '%affinity%' THEN 'Affinity' "
            "WHEN lower(general_name) LIKE '%tron%' THEN 'Tron' "
            "WHEN lower(general_name) IN ('bg gardens', 'bg pestilence') THEN 'BG Control' "
            "WHEN lower(general_name) IN ('mono red', 'red madness', 'red rally', 'red burn', 'br madness') THEN 'Burn' "
            "WHEN lower(general_name) IN ('blue terror', 'ub terror') THEN 'Terror' "
            "WHEN lower(general_name) IN ('blue faeries', 'ub faeries') THEN 'Faeries' "
            "ELSE NULL END"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_archetypes_macro_name", table_name="archetypes")
    op.drop_column("archetypes", "macro_name")
