"""enable Hobby Games AetherHub imports

Revision ID: 3c1587c33ad2
Revises: b4b96e826905
Create Date: 2026-08-17
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "3c1587c33ad2"
down_revision: Union[str, Sequence[str], None] = "b4b96e826905"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


IMPORT_TIMES = "17:30,18:00,18:30,19:00,19:30,20:00,20:30,21:00,21:30,22:00"

schedule = sa.table(
    "club_schedules",
    sa.column("club_name", sa.String),
    sa.column("weekday", sa.String),
    sa.column("import_times", sa.String),
)


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.update(schedule)
        .where(
            schedule.c.club_name == "Hobby Games",
            schedule.c.weekday == "saturday",
            schedule.c.import_times == "",
        )
        .values(import_times=IMPORT_TIMES)
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.update(schedule)
        .where(
            schedule.c.club_name == "Hobby Games",
            schedule.c.weekday == "saturday",
            schedule.c.import_times == IMPORT_TIMES,
        )
        .values(import_times="")
    )
