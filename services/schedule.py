"""Сервис расписания клубов — источник правды для планировщика (issue #124/#125).

Строки `club_schedules` редактируются админом из `/schedule`; код держит только дефолты
для первичного сида и идентичность клубов (см. `core/clubs.py`).
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.clubs import ClubIdentity, club_identities, default_schedules
from core.config import Club, ClubSchedule

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MAX_CREATE_DAYS_BEFORE = 6

# Индекс поля времени в callback карточки строки → имя (порядок стабилен, менять нельзя).
EDITABLE_TIME_FIELDS = ["create", "game", "reminder"]

WEEKDAY_RU = {
    "monday": "понедельник",
    "tuesday": "вторник",
    "wednesday": "среда",
    "thursday": "четверг",
    "friday": "пятница",
    "saturday": "суббота",
    "sunday": "воскресенье",
}


def create_offset_label(days_before: int) -> str:
    if days_before == 0:
        return "в день турнира"
    if days_before == 1:
        return "накануне"
    suffix = "дня" if 2 <= days_before <= 4 else "дней"
    return f"за {days_before} {suffix}"


def create_weekday(weekday: str, days_before: int) -> str:
    """Weekday on which the create job runs for an event weekday and offset."""
    if weekday not in WEEKDAYS:
        return weekday
    return WEEKDAYS[(WEEKDAYS.index(weekday) - days_before) % len(WEEKDAYS)]


def normalize_time(value: str) -> str | None:
    """'H:MM'/'HH:MM' → нормализованное 'HH:MM', или None если не валидно."""
    m = re.match(r"^(\d{1,2}):(\d{2})$", value.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return f"{h:02d}:{mi:02d}"


def _to_minutes(hhmm: str) -> int:
    h, mi = hhmm.split(":")
    return int(h) * 60 + int(mi)


def generate_import_times(start: str, end: str, step_min: int) -> list[str] | None:
    """Список времён импорта от start до end с шагом step_min (включительно), через полночь.

    end раньше start трактуется как «следующий день» (20:00→00:30). Возвращает None при
    бессмысленных параметрах (шаг < 5 мин или окно > суток).
    """
    if step_min < 5:
        return None
    start_m = _to_minutes(start)
    end_m = _to_minutes(end)
    if end_m <= start_m:
        end_m += 24 * 60  # окно переходит через полночь
    if end_m - start_m > 24 * 60:
        return None
    times = []
    t = start_m
    while t <= end_m:
        m = t % (24 * 60)
        times.append(f"{m // 60:02d}:{m % 60:02d}")
        t += step_min
    return times


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
                    create_days_before=d.create_days_before,
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

    def set_time_field(self, row_id: int, field: str, value: str) -> bool:
        """Ставит create_time/game_time (нормализованное `value`). Возвращает False, если строки нет."""
        row = self.get_row(row_id)
        if row is None:
            return False
        if field == "create":
            row.create_time = value
        elif field == "game":
            row.game_time = value
        else:
            raise ValueError(f"unknown time field: {field}")
        self.db.commit()
        return True

    def set_reminder(self, row_id: int, value: str | None) -> bool:
        """Ставит reminder_time (или None = выключить). Возвращает False, если строки нет."""
        row = self.get_row(row_id)
        if row is None:
            return False
        row.reminder_time = value
        self.db.commit()
        return True

    def set_create_days_before(self, row_id: int, days_before: int) -> bool:
        """Set how many days before the event its tournament is created."""
        if not 0 <= days_before <= MAX_CREATE_DAYS_BEFORE:
            raise ValueError(f"days_before must be between 0 and {MAX_CREATE_DAYS_BEFORE}")
        row = self.get_row(row_id)
        if row is None:
            return False
        row.create_days_before = days_before
        self.db.commit()
        return True

    def set_import_times(self, row_id: int, times: list[str]) -> bool:
        """Ставит список времён импорта (может быть пустым). Возвращает False, если строки нет."""
        row = self.get_row(row_id)
        if row is None:
            return False
        row.import_times = format_import_times(times)
        self.db.commit()
        return True

    def set_weekday(self, row_id: int, weekday: str) -> str:
        """Меняет день недели строки. Возвращает 'ok' / 'not_found' / 'duplicate'.

        'duplicate' — у этого клуба уже есть строка на такой день (нарушение уникальности
        (club_name, weekday)); молча сливать две строки в одну нельзя.
        """
        row = self.get_row(row_id)
        if row is None:
            return "not_found"
        if weekday == row.weekday:
            return "ok"
        clash = self.db.execute(
            select(models.ClubScheduleRow.id).where(
                models.ClubScheduleRow.club_name == row.club_name,
                models.ClubScheduleRow.weekday == weekday,
                models.ClubScheduleRow.id != row.id,
            )
        ).scalar_one_or_none()
        if clash is not None:
            return "duplicate"
        row.weekday = weekday
        self.db.commit()
        return "ok"

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
                    create_days_before=r.create_days_before,
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
        timezone=identity.timezone,
        schedules=schedules,
    )
