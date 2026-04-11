# Test Plan

## Текущий статус

**96 тестов, все проходят.** Общий coverage: ~81%.

```
tests/
├── conftest.py                   # фикстуры: SQLite in-memory DB, session, svc, базовые объекты
├── test_tournament_service.py    # 34 теста — бизнес-логика
├── test_scheduler.py             # 7 тестов — parse_schedule
├── test_seed.py                  # 4 теста — идемпотентность, корректность данных
├── test_messages.py              # 8 тестов — шаблоны и форматирование
├── test_keyboards.py             # 7 тестов — callback_data формат, структура кнопок
├── test_admin_actions.py         # 22 теста — handle_xxx функции admin.py (без Telegram)
└── test_player_actions.py        # 14 тестов — handle_xxx функции player.py (без Telegram)
```

## Паттерн тестирования handler'ов

Хендлеры разделены на два слоя:
- **`handle_xxx(db, ...primitives) → HandlerResult`** — чистая бизнес-логика, тестируется напрямую
- **`cmd_xxx / callback_xxx`** — тонкие Telegram-обёртки, вызывают `handle_xxx` и отправляют ответ

`HandlerResult` (`bot/handlers/base.py`):
```python
@dataclass
class HandlerResult:
    text: str
    keyboard: Optional[InlineKeyboardMarkup] = None
    is_alert: bool = False
```

## Покрытие по файлам

| Файл | Coverage | Статус |
|------|----------|--------|
| `core/models.py` | 100% | ✅ |
| `core/schemas.py` | 100% | ✅ |
| `bot/keyboards/__init__.py` | 100% | ✅ |
| `bot/messages/__init__.py` | 100% | ✅ |
| `bot/handlers/base.py` | 100% | ✅ |
| `services/errors.py` | 100% | ✅ |
| `services/utils.py` | 92% | ✅ |
| `services/tournament.py` | 88% | ✅ |
| `utils/seed.py` | 85% | ✅ |
| `core/config.py` | 85% | 🔶 |
| `bot/handlers/admin.py` | 64% | 🔶 handle_xxx покрыты, cmd_xxx — нет |
| `bot/scheduler.py` | 43% | 🔶 |
| `bot/handlers/player.py` | 41% | 🔶 handle_xxx покрыты, callbacks — нет |
| `bot/handlers/common.py` | 0% | ❌ |
| `main.py` | 0% | — не тестируется (точка входа) |

---

## Что можно добавить (по приоритету)

### Высокий — лёгкие тесты, нет зависимостей

#### `tests/test_config.py`
Непокрытые строки: properties `admin_ids`, `schedule_list`, `chat_ids`.

```python
test_admin_ids_parses_comma_separated      # "123,456" → [123, 456]
test_admin_ids_empty_string_returns_list   # "" → []
test_schedule_list_single_entry            # "friday 19:00" → ["friday 19:00"]
test_schedule_list_multiple_entries        # "friday 19:00,saturday 12:00" → [...]
test_chat_ids_parses_correctly             # "100,200" → [100, 200]
```

---

### Средний — требует моков

#### `tests/test_scheduler_job.py`
Покрыть `_create_tournaments_for_schedule` и `setup_scheduler`.

Подход: мокировать `bot.send_message`, `SessionLocal`, `TournamentService`.

```python
test_job_skips_wrong_weekday          # вызов в понедельник при schedule "friday" → ничего не делает
test_job_creates_tournament           # правильный день → create_tournament вызван
test_job_closes_previous_tournament   # если есть активный → close_tournament вызван
test_job_skips_empty_chat_ids         # TOURNAMENT_CHAT_IDS пуст → early return
test_job_continues_on_per_chat_error  # ошибка в одном чате не блокирует другие
```

---

### Низкий — требует Telegram-моков (cmd_xxx / callback_xxx обёртки)

Telegram-обёртки (`cmd_add_me`, `callback_register`, etc.) тестировать через `unittest.mock.AsyncMock`.
Покрывают только маршрутизацию аргументов — реальная логика уже покрыта в `test_admin_actions.py` и `test_player_actions.py`.

---

## Инфраструктура тестов

**Фикстуры** (`conftest.py`):
- `db` — чистая SQLite in-memory сессия на каждый тест (FK включены)
- `svc` — `TournamentService(db)`
- `tournament`, `user_alice`, `user_bob`, `archetype_burn`, `archetype_affinity` — готовые объекты

**Запуск:**
```bash
python3 -m pytest tests/                                              # все тесты
python3 -m pytest tests/ -v                                           # verbose
python3 -m pytest tests/ --cov=. --cov-report=term-missing --ignore=.venv  # с покрытием
python3 -m pytest tests/test_admin_actions.py -v                      # один файл
python3 -m pytest tests/test_tournament_service.py::TestCastVote -v  # один класс
```

**Зависимости:** PostgreSQL не нужен — SQLite in-memory. `pytest`, `pytest-cov`, `pytest-asyncio` в `requirements.txt`.
