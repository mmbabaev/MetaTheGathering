"""expand macro archetype families

Revision ID: 205dd0048c4c
Revises: 53868428fae8
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "205dd0048c4c"
down_revision: Union[str, Sequence[str], None] = "53868428fae8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Подтверждённые варианты турнира Edinorog Pauper 10.08.2026. Меняем только
    # отдельные classification-поля; пользовательские name и participant links не трогаем.
    op.execute(
        sa.text(
            "UPDATE archetypes SET general_name = CASE lower(name) "
            "WHEN 'uw fam' THEN 'UW Familiars' "
            "WHEN 'monoblack sacrifice' THEN 'Black Sacrifice' "
            "WHEN 'rainbow black sac' THEN 'Black Sacrifice' "
            "WHEN 'selesnya turbo initiative' THEN 'WG Turbo Initiative' "
            "ELSE general_name END "
            "WHERE lower(name) IN ("
            "'uw fam', 'monoblack sacrifice', 'rainbow black sac', "
            "'selesnya turbo initiative')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE archetypes SET macro_name = CASE "
            "WHEN lower(general_name) = 'bogles' THEN 'Bogles' "
            "WHEN lower(general_name) = 'ephemerate' "
            "  OR lower(general_name) LIKE '% ephemerate' THEN 'Ephemerate' "
            "WHEN lower(general_name) = 'spy walls' THEN 'Walls' "
            "WHEN lower(general_name) IN ('sacrifice', 'black sacrifice') "
            "  THEN 'Sacrifice' "
            "ELSE macro_name END "
            "WHERE lower(general_name) = 'bogles' "
            "OR lower(general_name) = 'ephemerate' "
            "OR lower(general_name) LIKE '% ephemerate' "
            "OR lower(general_name) = 'spy walls' "
            "OR lower(general_name) IN ('sacrifice', 'black sacrifice')"
        )
    )


def downgrade() -> None:
    # Classification backfills are intentionally data-preserving on downgrade.
    pass
