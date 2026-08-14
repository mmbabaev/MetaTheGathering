"""add Pair of dice schedules

Revision ID: d05d9619e6af
Revises: 4b2a49905e82
Create Date: 2026-08-14
"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d05d9619e6af"
down_revision: Union[str, Sequence[str], None] = "4b2a49905e82"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_IMPORT_TIMES = "20:00,20:30,21:00,21:30,22:00,22:30,23:00,23:30,00:00,00:30"

schedule = sa.table(
    "club_schedules",
    sa.column("club_name", sa.String),
    sa.column("weekday", sa.String),
    sa.column("enabled", sa.Boolean),
    sa.column("create_time", sa.String),
    sa.column("game_time", sa.String),
    sa.column("reminder_time", sa.String),
    sa.column("import_times", sa.String),
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
)


def _row(club_name: str, weekday: str, *, source: dict | None = None) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    source = source or {}
    return {
        "club_name": club_name,
        "weekday": weekday,
        "enabled": True,
        "create_time": source.get("create_time", "12:00"),
        "game_time": source.get("game_time", "19:30"),
        "reminder_time": source.get("reminder_time", "19:25"),
        "import_times": source.get("import_times", DEFAULT_IMPORT_TIMES),
        "created_at": now,
        "updated_at": now,
    }


def upgrade() -> None:
    connection = op.get_bind()
    row_count = connection.execute(sa.select(sa.func.count()).select_from(schedule)).scalar_one()

    if row_count == 0:
        # На новой БД миграция выполняется до startup-сидера, поэтому создаём полный
        # актуальный набор: иначе ensure_defaults() увидит непустую таблицу и пропустит старые клубы.
        connection.execute(
            sa.insert(schedule),
            [
                _row("Goldfish", "friday", source={"game_time": "19:45", "reminder_time": "19:45"}),
                _row("Edinorog", "monday"),
                _row("Edinorog", "thursday"),
                _row("Pair of dice", "monday"),
                _row("Pair of dice", "wednesday"),
            ],
        )
        return

    edinorog_monday = (
        connection.execute(
            sa.select(
                schedule.c.create_time,
                schedule.c.game_time,
                schedule.c.reminder_time,
                schedule.c.import_times,
            ).where(schedule.c.club_name == "Edinorog", schedule.c.weekday == "monday")
        )
        .mappings()
        .first()
    )
    source = dict(edinorog_monday) if edinorog_monday else None

    for weekday in ("monday", "wednesday"):
        exists = connection.execute(
            sa.select(sa.func.count())
            .select_from(schedule)
            .where(
                schedule.c.club_name == "Pair of dice",
                schedule.c.weekday == weekday,
            )
        ).scalar_one()
        if not exists:
            connection.execute(sa.insert(schedule).values(**_row("Pair of dice", weekday, source=source)))


def downgrade() -> None:
    op.get_bind().execute(sa.delete(schedule).where(schedule.c.club_name == "Pair of dice"))
