"""add Hobby Games Kaliningrad schedule

Revision ID: b4b96e826905
Revises: 9b5e1ed436ed
Create Date: 2026-08-17
"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b4b96e826905"
down_revision: Union[str, Sequence[str], None] = "9b5e1ed436ed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


schedule = sa.table(
    "club_schedules",
    sa.column("club_name", sa.String),
    sa.column("weekday", sa.String),
    sa.column("enabled", sa.Boolean),
    sa.column("create_time", sa.String),
    sa.column("create_days_before", sa.Integer),
    sa.column("game_time", sa.String),
    sa.column("reminder_time", sa.String),
    sa.column("import_times", sa.String),
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
)


def upgrade() -> None:
    connection = op.get_bind()
    exists = connection.execute(
        sa.select(sa.func.count())
        .select_from(schedule)
        .where(schedule.c.club_name == "Hobby Games", schedule.c.weekday == "saturday")
    ).scalar_one()
    if exists:
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    connection.execute(
        sa.insert(schedule).values(
            club_name="Hobby Games",
            weekday="saturday",
            enabled=True,
            create_time="18:30",
            create_days_before=1,
            game_time="17:00",
            reminder_time="16:55",
            import_times="",
            created_at=now,
            updated_at=now,
        )
    )


def downgrade() -> None:
    op.get_bind().execute(sa.delete(schedule).where(schedule.c.club_name == "Hobby Games"))
