"""repair legacy macro cache from confirmed raw names

Revision ID: f24df28a306e
Revises: 205dd0048c4c
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f24df28a306e"
down_revision: Union[str, Sequence[str], None] = "205dd0048c4c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Некоторые старые debug/production-строки появились до general_name и сохранили
    # NULL. Восстанавливаем оба classification-слоя по точным названиям из турнира;
    # исходные name и ссылки участников остаются нетронутыми.
    op.execute(
        sa.text(
            "UPDATE archetypes SET general_name = CASE lower(name) "
            "WHEN 'bogles' THEN 'Bogles' "
            "WHEN '🟢🔵🐸 bogles' THEN 'Bogles' "
            "WHEN 'jeskai ephemerate' THEN 'Jeskai Ephemerate' "
            "WHEN 'spy combo' THEN 'Spy Walls' "
            "WHEN 'spy walls' THEN 'Spy Walls' "
            "WHEN 'uw fam' THEN 'UW Familiars' "
            "WHEN 'monoblack sacrifice' THEN 'Black Sacrifice' "
            "WHEN 'rainbow black sac' THEN 'Black Sacrifice' "
            "WHEN 'selesnya turbo initiative' THEN 'WG Turbo Initiative' "
            "ELSE general_name END "
            "WHERE lower(name) IN ("
            "'bogles', '🟢🔵🐸 bogles', 'jeskai ephemerate', 'spy combo', "
            "'spy walls', 'uw fam', 'monoblack sacrifice', 'rainbow black sac', "
            "'selesnya turbo initiative')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE archetypes SET macro_name = CASE lower(name) "
            "WHEN 'bogles' THEN 'Bogles' "
            "WHEN '🟢🔵🐸 bogles' THEN 'Bogles' "
            "WHEN 'jeskai ephemerate' THEN 'Ephemerate' "
            "WHEN 'spy combo' THEN 'Walls' "
            "WHEN 'spy walls' THEN 'Walls' "
            "WHEN 'monoblack sacrifice' THEN 'Sacrifice' "
            "WHEN 'rainbow black sac' THEN 'Sacrifice' "
            "ELSE macro_name END "
            "WHERE lower(name) IN ("
            "'bogles', '🟢🔵🐸 bogles', 'jeskai ephemerate', 'spy combo', "
            "'spy walls', 'monoblack sacrifice', 'rainbow black sac')"
        )
    )


def downgrade() -> None:
    # Classification repairs are intentionally data-preserving on downgrade.
    pass
