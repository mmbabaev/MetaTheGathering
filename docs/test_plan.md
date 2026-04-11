# Test Plan

## Текущий статус

**60 тестов, все проходят.** Общий coverage: ~65%.

```
tests/
├── conftest.py                   # фикстуры: SQLite in-memory DB, session, svc, базовые объекты
├── test_tournament_service.py    # 34 теста — бизнес-логика
├── test_scheduler.py             # 7 тестов — parse_schedule
├── test_seed.py                  # 4 теста — идемпотентность, корректность данных
├── test_messages.py              # 8 тестов — шаблоны и форматирование
└── test_keyboards.py             # 7 тестов — callback_data формат, структура кнопок
```

## Покрытие по файлам

| Файл | Coverage | Статус |
|------|----------|--------|
| `core/models.py` | 100% | ✅ |
| `core/schemas.py` | 100% | ✅ |
| `bot/keyboards/__init__.py` | 100% | ✅ |
| `bot/messages/__init__.py` | 100% | ✅ |
| `services/errors.py` | 100% | ✅ |
| `services/utils.py` | 92% | ✅ |
| `services/tournament.py` | 88% | ✅ |
| `utils/seed.py` | 85% | ✅ |
| `core/config.py` | 85% | 🔶 |
| `bot/scheduler.py` | 43% | 🔶 |
| `bot/handlers/admin.py` | 0% | ❌ |
| `bot/handlers/player.py` | 0% | ❌ |
| `bot/handlers/common.py` | 0% | ❌ |
| `main.py` | 0% | — не тестируется (точка входа) |

---

## Что добавить (по приоритету)

### Высокий — лёгкие тесты, нет зависимостей

#### `tests/test_config.py`
Непокрытые строки: properties `admin_ids`, `schedule_list`, `chat_ids`.

```python
# Примеры тестов
test_admin_ids_parses_comma_separated      # "123,456" → [123, 456]
test_admin_ids_empty_string_returns_list   # "" → []
test_schedule_list_single_entry            # "friday 19:00" → ["friday 19:00"]
test_schedule_list_multiple_entries        # "friday 19:00,saturday 12:00" → [...]
test_chat_ids_parses_correctly             # "100,200" → [100, 200]
```

#### Дополнения в `test_tournament_service.py`
Непокрытые методы в `services/tournament.py`:

| Метод | Тесты |
|-------|-------|
| `get_active_tournament_for_chat` | возвращает None если нет активных; возвращает турнир |
| `list_tournaments_for_chat` | возвращает все турниры чата (включая закрытые) |
| `list_archetypes` | возвращает список, сортировка по имени |
| `open_registration` | меняет статус на REGISTRATION |
| `cast_vote` — несуществующий voter | `VotingNotAllowed` |

#### Дополнения в `test_utils.py`
```python
test_get_tournament_not_found   # TournamentNotFound при несуществующем ID
```

---

### Средний — требует моков

#### `tests/test_scheduler_job.py`
Покрыть `scheduled_tournament_job` и `setup_scheduler`.

Подход: мокировать `context.bot.send_message`, `SessionLocal`, `TournamentService`.

```python
# Примеры тестов
test_job_skips_wrong_weekday          # вызов в понедельник при schedule "friday" → ничего не делает
test_job_creates_tournament           # правильный день → create_tournament вызван
test_job_closes_previous_tournament   # если есть активный → close_tournament вызван
test_job_skips_empty_chat_ids         # TOURNAMENT_CHAT_IDS пуст → early return
test_job_continues_on_per_chat_error  # ошибка в одном чате не блокирует другие
```

---

### Низкий — требует Telegram-моков, сложно

#### `tests/test_handlers_admin.py`, `test_handlers_player.py`, `test_handlers_common.py`

Требуют мока `telegram.Update` и `telegram.ext.ContextTypes`.
Подход: `unittest.mock.AsyncMock` + создание минимальных заглушек для `update.effective_user`, `update.effective_message`, `update.effective_chat`.

```python
# Примеры тестов для admin.py
test_add_me_non_admin_returns_not_admin_msg
test_add_me_no_args_returns_usage_msg
test_add_me_no_active_tournament
test_add_me_registers_successfully
test_add_player_user_not_found
test_add_player_success
test_add_players_bulk_mixed_results
test_tournament_status_shows_participants
test_close_tournament_success
```

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
python3 -m pytest tests/test_tournament_service.py::TestCastVote -v  # один класс
```

**Зависимости:** PostgreSQL не нужен — SQLite in-memory. `pytest`, `pytest-cov`, `pytest-asyncio` в `requirements.txt`.
