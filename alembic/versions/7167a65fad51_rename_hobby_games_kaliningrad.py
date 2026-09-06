"""rename Hobby Games club to Hobby Games - Kaliningrad

Revision ID: 7167a65fad51
Revises: 572aa2e07c0c
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "7167a65fad51"
down_revision: Union[str, Sequence[str], None] = "572aa2e07c0c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_NAME = "Hobby Games"
NEW_NAME = "Hobby Games - Калининград"


def _rename(old_name: str, new_name: str) -> None:
    tables_and_columns = (
        ("tournaments", "club"),
        ("club_schedules", "club_name"),
        ("club_settings", "club_name"),
        ("tournament_creation_plans", "club_name"),
        ("club_announcement_settings", "club_name"),
    )
    connection = op.get_bind()
    for table_name, column_name in tables_and_columns:
        table = sa.table(table_name, sa.column(column_name, sa.String(length=64)))
        connection.execute(
            sa.update(table).where(getattr(table.c, column_name) == old_name).values({column_name: new_name})
        )


def upgrade() -> None:
    _rename(OLD_NAME, NEW_NAME)


def downgrade() -> None:
    _rename(NEW_NAME, OLD_NAME)
