"""add club_schedules

Расписание клубов переезжает из кода в БД (issue #124/#125). Таблицу заполняет
ScheduleService.ensure_defaults() при старте бота — из дефолтов в коде, поэтому
миграция строк не вставляет: так сид всегда соответствует актуальному коду.

Revision ID: 7c178567f22c
Revises: 7f446c079123
Create Date: 2026-07-23

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "7c178567f22c"
down_revision: Union[str, Sequence[str], None] = "7f446c079123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "club_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("club_name", sa.String(length=64), nullable=False),
        sa.Column("weekday", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("create_time", sa.String(length=5), nullable=False),
        sa.Column("game_time", sa.String(length=5), nullable=False),
        sa.Column("reminder_time", sa.String(length=5), nullable=True),
        sa.Column("import_times", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("club_name", "weekday", name="uq_club_schedule_day"),
    )
    op.create_index("ix_club_schedules_club_name", "club_schedules", ["club_name"])


def downgrade() -> None:
    op.drop_index("ix_club_schedules_club_name", table_name="club_schedules")
    op.drop_table("club_schedules")
