# Рефактор: разделение Club и TournamentConfig

## Проблема

Текущая структура `Club + ClubSchedule` смешивает два уровня:
- Клуб (постоянная сущность: название, чат, страница AetherHub)
- Конкретный турнир (расписание, заголовок, время создания)

Goldfish сейчас имеет два `ClubSchedule` (четверг + пятница), но заголовок и chat_id
задаются на уровне `Club`, хотя логически они принадлежат конкретному турниру.
В будущем может понадобиться разный заголовок или даже разный чат для турниров одного клуба.

## Целевая структура

### `Club` — общие данные клуба

```python
@dataclass
class Club:
    name: str
    aetherhub_url: Optional[str] = None  # страница клуба на AetherHub
```

Клуб — просто источник данных. Не знает ни про чат, ни про расписание.

### `TournamentConfig` — конфиг одного регулярного турнира

```python
@dataclass
class TournamentConfig:
    title: str            # "🐠 Goldfish Pauper" — без даты, дата добавляется при создании
    club: Club            # ссылка на клуб (берём aetherhub_url)
    chat_id: int          # Telegram chat_id для этого турнира
    weekday: str          # "friday"
    game_time: str        # "19:45"
    create_time: Optional[str] = None          # если None — берётся из settings
    aetherhub_fetch_times: List[str] = field(default_factory=list)
    find_latest: bool = False                  # debug: игнорировать дату
```

### Пример конфигурации

```python
GOLDFISH = Club(
    name="Goldfish",
    aetherhub_url="https://aetherhub.com/User/GoldFish",
)

EDINOROG = Club(
    name="Edinorog",
    aetherhub_url="https://aetherhub.com/User/Edinorog/",
)

TOURNAMENT_CONFIGS = [
    TournamentConfig(
        title="🐠 Goldfish Pauper",
        club=GOLDFISH,
        chat_id=-1001399656692,
        weekday="thursday",
        game_time="19:45",
        create_time="03:10",
        aetherhub_fetch_times=["20:00", "20:30", ...],
    ),
    TournamentConfig(
        title="🐠 Goldfish Pauper",
        club=GOLDFISH,
        chat_id=-1001399656692,
        weekday="friday",
        game_time="19:45",
        create_time="12:00",
        aetherhub_fetch_times=["20:00", "20:30", ...],
    ),
    TournamentConfig(
        title="🦄 Edinorog Pauper",
        club=EDINOROG,
        chat_id=...,
        weekday="monday",
        game_time="19:30",
        aetherhub_fetch_times=["20:00", ...],
    ),
]
```

## Изменения в scheduler.py

- `get_clubs()` → `get_tournament_configs() -> list[TournamentConfig]`
- `CreateTournamentJob(club, schedule)` → `CreateTournamentJob(config: TournamentConfig)`
- `AetherhubImportJob(club, schedule)` → `AetherhubImportJob(config: TournamentConfig)`
- В `CreateTournamentJob.run()`:
  - title строится как `f"{config.title} {now.strftime('%d.%m.%Y')}"`
  - slug: `f"{date_str}-{config.club.name.lower()}-pauper-{config.weekday}"`
  - `club` в БД = `config.club.name` (как сейчас)
- `_find_active_club_tournament(db, club_name)` → может остаться, ищет по `club` полю

## Что не меняется

- БД-модель `Tournament` — поле `club` остаётся строкой (название клуба)
- Логика AetherHub fetch (`aetherhub_url` теперь берётся из `config.club.aetherhub_url`)
- `format_schedule_text()` переписывается под новую структуру

## Что улучшается

- У каждого турнира свой `chat_id` и `title` — можно турниры одного клуба вести в разных чатах
- Нет дублирования `chat_id` и `title_prefix` на уровне клуба
- Debug конфиг читается чище: один `TournamentConfig` с `find_latest=True`
- `_format_club_schedule()` можно упростить — итерируемся по конфигам, не по клубам

## Порядок выполнения

1. Добавить `TournamentConfig` в `core/config.py`, убрать `title_prefix` из `Club`
2. Переписать `get_clubs()` → `get_tournament_configs()` в `scheduler.py`
3. Обновить `CreateTournamentJob` и `AetherhubImportJob`
4. Обновить `format_schedule_text()` и `_format_club_schedule()`
5. Обновить тесты
