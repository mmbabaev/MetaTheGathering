"""Идентичность клубов и дефолтное расписание (issue #124/#125).

Разделение ответственности:
  * **идентичность клуба** (chat_id, ссылка на AetherHub, эмодзи) — инфраструктура, живёт в коде;
  * **расписание** (дни, времена, вкл/выкл) — данные, живут в БД (`club_schedules`) и правятся
    админом из `/schedule`. Дефолты ниже нужны только для первичного сида пустой таблицы.

Модуль намеренно не импортирует ни `services`, ни `bot` — иначе получится цикл
(`bot.scheduler` → `services.schedule` → `core.clubs`).
"""

from dataclasses import dataclass

from core.config import Club, ClubSchedule, app_cfg, settings

# Импорты с AetherHub: каждые 30 минут с начала игры до полуночи с хвостом.
DEFAULT_IMPORT_TIMES = [
    "20:00",
    "20:30",
    "21:00",
    "21:30",
    "22:00",
    "22:30",
    "23:00",
    "23:30",
    "00:00",
    "00:30",
]


@dataclass(frozen=True)
class ClubIdentity:
    """Постоянные атрибуты клуба — то, что расписанием не управляется."""

    name: str
    chat_id: int
    aetherhub_url: str | None
    title_prefix: str


def club_identities() -> list[ClubIdentity]:
    """Клубы, расписание которых управляется через БД/UI."""
    return [
        ClubIdentity(
            name="Goldfish",
            chat_id=app_cfg.goldfish_chat_id or 0,
            aetherhub_url="https://aetherhub.com/User/GoldFish",
            title_prefix="🐠 ",
        ),
        ClubIdentity(
            name="Edinorog",
            chat_id=app_cfg.edinorog_chat_id or 0,
            aetherhub_url="https://aetherhub.com/User/Edinorog/",
            title_prefix="🦄 ",
        ),
    ]


@dataclass(frozen=True)
class DefaultSchedule:
    """Строка дефолтного расписания для сида пустой таблицы."""

    club_name: str
    weekday: str
    create_time: str
    game_time: str
    reminder_time: str | None
    import_times: list[str]


def default_schedules() -> list[DefaultSchedule]:
    """Расписание «как было в коде» — засевается один раз, дальше правится в UI."""
    return [
        DefaultSchedule("Goldfish", "friday", "12:00", "19:45", "19:45", list(DEFAULT_IMPORT_TIMES)),
        DefaultSchedule("Edinorog", "monday", "12:00", "19:30", "19:25", list(DEFAULT_IMPORT_TIMES)),
        DefaultSchedule("Edinorog", "thursday", "12:00", "19:30", "19:25", list(DEFAULT_IMPORT_TIMES)),
    ]


def default_clubs() -> list[Club]:
    """Клубы с дефолтным расписанием из кода — фоллбек, если БД недоступна или пуста."""
    by_name: dict[str, list[ClubSchedule]] = {}
    for d in default_schedules():
        by_name.setdefault(d.club_name, []).append(
            ClubSchedule(
                weekday=d.weekday,
                game_time=d.game_time,
                create_time=d.create_time,
                reminder_time=d.reminder_time,
                aetherhub_fetch_times=list(d.import_times),
            )
        )
    return [
        Club(
            name=i.name,
            chat_id=i.chat_id,
            aetherhub_url=i.aetherhub_url,
            title_prefix=i.title_prefix,
            schedules=by_name.get(i.name, []),
        )
        for i in club_identities()
    ]


def debug_club() -> Club | None:
    """Отладочный клуб — только при DEBUG, расписанием из БД НЕ управляется.

    Держим в коде специально: `find_latest` и «сыграть прямо сейчас» — свойства отладки,
    в UI админа им делать нечего.
    """
    if not settings.DEBUG:
        return None
    return Club(
        name="Debug",
        chat_id=app_cfg.goldfish_chat_id or 0,
        aetherhub_url="https://aetherhub.com/User/GoldFish",
        title_prefix="[DEBUG] 🐠 ",
        schedules=[
            ClubSchedule(
                weekday="thursday",
                game_time="12:30",
                create_time="12:30",
                aetherhub_fetch_times=["12:31"],
                find_latest=True,
            )
        ],
    )
