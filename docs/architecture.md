# Architecture

## Stack

| Компонент | Версия |
|-----------|--------|
| python-telegram-bot | >=21.0 |
| SQLAlchemy | 2.x |
| Alembic | 1.x |
| Pydantic + pydantic-settings | v2 |
| psycopg2-binary | PostgreSQL driver |
| cloudscraper + beautifulsoup4 | AetherHub scraping |
| rapidfuzz + transliterate | Fuzzy archetype matching |
| openpyxl | Excel export |
| pytest + pytest-asyncio | 553 тестов, SQLite in-memory |

## Структура файлов

```
MetaGatherer/
├── main.py                        # Точка входа — регистрирует хендлеры, запускает polling
├── server.sh                      # Управление процессом (start/stop/status/logs)
├── bot/
│   ├── telegram/                  # Тонкие async-обёртки: извлекают примитивы из Update, вызывают handle_xxx
│   │   ├── admin.py
│   │   ├── aetherhub.py
│   │   ├── common.py
│   │   ├── player.py
│   │   ├── poll.py
│   │   └── settings.py
│   ├── handlers/                  # Чистая бизнес-логика: handle_xxx(db, ...primitives) → HandlerResult
│   │   ├── base.py                # HandlerResult dataclass
│   │   ├── admin.py
│   │   ├── common.py
│   │   ├── player.py
│   │   ├── settings.py
│   │   └── voting.py
│   ├── keyboards/                 # CB_* константы + построители inline-клавиатур
│   ├── messages/                  # Русские строки + format_* хелперы
│   ├── middlewares/               # (пусто)
│   ├── scheduler.py               # APScheduler — создаёт турниры по расписанию
│   └── deck_emoji.py
├── services/
│   ├── tournament.py              # Основной сервис: жизненный цикл, регистрация, голосование, мета
│   ├── aetherhub.py               # Скрапер AetherHub (cloudscraper + BS4)
│   ├── aetherhub_import.py        # Импорт истории колод из AetherHub
│   ├── archetype.py               # Поиск архетипа (fuzzy + транслитерация)
│   ├── export.py                  # Экспорт CSV/Markdown/Excel
│   ├── poll.py                    # Telegram-опросы (пойду/не пойду)
│   ├── stats.py                   # Статистика
│   ├── user.py                    # Управление пользователями
│   ├── voting.py                  # (заглушка — логика в tournament.py)
│   ├── errors.py                  # Реэкспорт из services_errors.py
│   └── utils.py                   # ensure_tournament_status, хелперы
├── core/
│   ├── models.py                  # SQLAlchemy ORM (9 таблиц)
│   ├── schemas.py                 # Pydantic v2 схемы (read/create)
│   ├── database.py                # SessionLocal, Base
│   ├── config.py                  # Настройки через pydantic-settings
│   └── event_log.py               # Лог событий (JSONL)
├── config/
│   ├── prod.py                    # Конфигурация клубов/расписаний для прода
│   └── debug.py                   # Конфигурация для дебага
├── utils/
│   ├── seed.py                    # Начальные данные (архетипы)
│   ├── import_players.py          # Массовый импорт игроков
│   ├── formatters.py              # Форматирование таблиц
│   └── validators.py              # Валидация ввода
├── scripts/                       # Разовые/утилитарные скрипты
│   ├── aetherhub/
│   ├── datalens_parser/
│   └── telegram_parser/
├── web/api/                       # Не реализовано
├── alembic/                       # Миграции БД
├── tests/                         # 553 теста (SQLite in-memory)
└── .github/workflows/             # CI/CD: deploy.yml (прод), pr.yml (дебаг)
```

## Слои

```
main.py  →  bot/telegram/  →  bot/handlers/  →  services/  →  core/models + database
```

- **`bot/telegram/`** — не тестируется, не содержит логики
- **`bot/handlers/`** — чистые функции, 100% покрыты тестами
- **`services/tournament.py`** — основная бизнес-логика
- **`core/`** — модели, схемы, конфиг

## Деплой

GitHub Actions (`.github/workflows/`):
- push в `main` → деплой на прод
- открытый PR → деплой в дебаг-окружение

На сервере: systemd-сервисы (`bot/systemd/`). `docker-compose.yml` в репо есть, в проде не используется.

> **Важно:** не запускать бота локально с прод-токеном — конфликт с проиводственным инстансом.
