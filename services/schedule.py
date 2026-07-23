"""Сервис расписания клубов — источник правды для планировщика (issue #124/#125).

Строки `club_schedules` редактируются админом из `/schedule`; код держит только дефолты
для первичного сида и идентичность клубов (см. `core/clubs.py`).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.clubs import ClubIdentity, club_identities, default_schedules
from core.config import Club, ClubSchedule

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

WEEKDAY_RU = {
    "monday": "понедельник",
    "tuesday": "вторник",
    "wednesday": "среда",
    "thursday": "четверг",
    "friday": "пятница",
    "saturday": "суббота",
    "sunday": "воскресенье",
}


def parse_import_times(csv: str | None) -> list[str]:
    """CSV → список времён, пустые куски отбрасываем."""
    if not csv:
        return []
    return [part.strip() for part in csv.split(",") if part.strip()]


def format_import_times(times: list[str]) -> str:
    return ",".join(times)


class ScheduleService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- чтение ---

    def list_rows(self) -> list[models.ClubScheduleRow]:
        """Все строки расписания в порядке «клуб → день недели»."""
        rows = self.db.execute(select(models.ClubScheduleRow)).scalars().all()
        order = {name: i for i, name in enumerate(c.name for c in club_identities())}
        return sorted(
            rows,
            key=lambda r: (order.get(r.club_name, 99), WEEKDAYS.index(r.weekday) if r.weekday in WEEKDAYS else 99),
        )

    def get_row(self, row_id: int) -> models.ClubScheduleRow | None:
        return self.db.get(models.ClubScheduleRow, row_id)

    # --- сид ---

    def ensure_defaults(self) -> int:
        """Засевает расписание из кода, если таблица пуста. Возвращает число созданных строк.

        Сеем ТОЛЬКО когда таблица пуста целиком: иначе удалённая админом строка
        воскресала бы при каждом рестарте бота.
        """
        existing = self.db.execute(select(models.ClubScheduleRow.id).limit(1)).scalar_one_or_none()
        if existing is not None:
            return 0
        created = 0
        for d in default_schedules():
            self.db.add(
                models.ClubScheduleRow(
                    club_name=d.club_name,
                    weekday=d.weekday,
                    enabled=True,
                    create_time=d.create_time,
                    game_time=d.game_time,
                    reminder_time=d.reminder_time,
                    import_times=format_import_times(d.import_times),
                )
            )
            created += 1
        self.db.commit()
        return created

    # --- правка ---

    def toggle_enabled(self, row_id: int) -> bool | None:
        """Инвертирует enabled. Возвращает новое значение или None, если строки нет."""
        row = self.get_row(row_id)
        if row is None:
            return None
        row.enabled = not row.enabled
        self.db.commit()
        return bool(row.enabled)

    # --- сборка клубов для планировщика ---

    def build_clubs(self) -> list[Club]:
        """Клубы с расписанием из БД. Выключенные строки не попадают — джоб для них не будет."""
        rows = [r for r in self.list_rows() if r.enabled]
        by_name: dict[str, list[ClubSchedule]] = {}
        for r in rows:
            by_name.setdefault(r.club_name, []).append(
                ClubSchedule(
                    weekday=r.weekday,
                    game_time=r.game_time,
                    create_time=r.create_time,
                    reminder_time=r.reminder_time,
                    aetherhub_fetch_times=parse_import_times(r.import_times),
                )
            )
        return [_to_club(identity, by_name.get(identity.name, [])) for identity in club_identities()]


def _to_club(identity: ClubIdentity, schedules: list[ClubSchedule]) -> Club:
    return Club(
        name=identity.name,
        chat_id=identity.chat_id,
        aetherhub_url=identity.aetherhub_url,
        title_prefix=identity.title_prefix,
        schedules=schedules,
    )
