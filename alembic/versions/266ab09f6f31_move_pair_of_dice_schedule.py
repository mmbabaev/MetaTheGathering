"""move Pair of dice schedule and open registration one day early

Revision ID: 266ab09f6f31
Revises: d05d9619e6af
Create Date: 2026-08-14
"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "266ab09f6f31"
down_revision: Union[str, Sequence[str], None] = "d05d9619e6af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TUESDAY_IMPORT_TIMES = "20:00,20:30,21:00,21:30,22:00,22:30,23:00,23:30,00:00,00:30"
SUNDAY_IMPORT_TIMES = "14:00,14:30,15:00,15:30,16:00,16:30,17:00,17:30,18:00,18:30"


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


def _row(weekday: str, game_time: str, reminder_time: str, import_times: str, now: datetime) -> dict:
    return {
        "club_name": "Pair of dice",
        "weekday": weekday,
        "enabled": True,
        "create_time": "18:30",
        "create_days_before": 1,
        "game_time": game_time,
        "reminder_time": reminder_time,
        "import_times": import_times,
        "created_at": now,
        "updated_at": now,
    }


def upgrade() -> None:
    op.add_column(
        "club_schedules",
        sa.Column("create_days_before", sa.Integer(), server_default="0", nullable=False),
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    connection = op.get_bind()
    # Replace both rows atomically so a prior manual weekday edit cannot create a
    # uniqueness collision or leave an obsolete Pair of dice event behind.
    connection.execute(sa.delete(schedule).where(schedule.c.club_name == "Pair of dice"))
    connection.execute(
        sa.insert(schedule),
        [
            _row("tuesday", "19:30", "19:25", TUESDAY_IMPORT_TIMES, now),
            _row("sunday", "13:30", "13:25", SUNDAY_IMPORT_TIMES, now),
        ],
    )


def downgrade() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    connection = op.get_bind()
    connection.execute(sa.delete(schedule).where(schedule.c.club_name == "Pair of dice"))
    connection.execute(
        sa.insert(schedule),
        [
            {
                **_row("monday", "19:30", "19:25", TUESDAY_IMPORT_TIMES, now),
                "create_time": "12:00",
                "create_days_before": 0,
            },
            {
                **_row("wednesday", "19:30", "19:25", TUESDAY_IMPORT_TIMES, now),
                "create_time": "12:00",
                "create_days_before": 0,
            },
        ],
    )
    op.drop_column("club_schedules", "create_days_before")
