# Debug CLI

Локальный инструмент для работы с debug-базой данных и тестирования флоу бота.
Переиспользует слой `services/` напрямую — та же логика, что и у бота.

**Всегда использует `bot/.env.debug`** (база `meta_the_gathering_debug`, `BOT_ENV=debug` проставляется автоматически).

## Установка

База должна существовать локально. Если ещё не создана:

```bash
createdb -U mbabaev meta_the_gathering_debug
BOT_ENV=debug python3 -m alembic upgrade head
```

## Команды

```
python3 cli.py tournament list           # список последних 10 турниров
python3 cli.py tournament create <title> # создать турнир
python3 cli.py tournament delete-last    # удалить последний по дате создания
python3 cli.py tournament import <url>   # импорт с AetherHub
python3 cli.py tournament export-excel   # выгрузить Excel в текущую папку
python3 cli.py endstep find <nick>       # точный поиск в Endstep Pauper Ranked
python3 cli.py swiss setup               # debug-турнир + 110 фейковых игроков
python3 cli.py swiss run --id 42         # прогнать все Swiss-раунды с рандомными результатами
python3 cli.py swiss finish --id 42      # закрыть турнир и расставить места
```

### Симулятор внутреннего Swiss

Только при `BOT_ENV=debug` и только для `app_cfg.endstep_ru_chat_id`. Гоняет настоящий
движок `InternalSwissService` — свои правила Swiss не дублируются.

Фейковые игроки получают отрицательный `tg_id`, `added_by_admin=True`, архетип и заполненный
деклист, поэтому уведомления и напоминания о деклистах им уйти не могут.

```bash
python3 cli.py swiss setup --players 110 --rounds 7
python3 cli.py swiss fill --id 42 --players 64   # долить игроков до первого раунда
python3 cli.py swiss step --id 42                # один раунд: заполнить результаты + создать следующий
python3 cli.py swiss run --id 42                 # все запланированные раунды, включая плей-офф
python3 cli.py swiss finish --id 42              # места и статус CLOSED
python3 cli.py swiss status --id 42
python3 cli.py swiss standings --id 42
python3 cli.py swiss close-active                # закрыть активные турниры клуба (нужно > 2)
```

`close-active` закрывает турниры независимо от числа сыгранных раундов и не расставляет места —
это эквивалент кнопок «🧹 Закрыть турнир» / «🧹 Освободить слоты» в debug-боте. Обычное
`swiss finish` требует сыграть и засчитать все запланированные раунды.

По умолчанию: `--players 110`, `--rounds 7` (7 Swiss-раундов + плей-офф Top-8 из 3 раундов,
всего 10 запланированных раундов), `--playoff 8`.
`run` играет и засчитывает все раунды, но **не** завершает турнир — `finish` вызывается отдельно.
Актор (`--admin-id`, по умолчанию `OWNER_CHAT_ID`) должен иметь права организатора.
`setup` не удаляет существующие турниры: если активных уже два, сначала нужен `close-active`.

### Поиск игроков Endstep

Клиент автоматически использует штатный `Continue as Guest` и не требует логина
или пароля. Передайте один или несколько точных ников:

```bash
python3 cli.py endstep find PlayerOne PlayerTwo
python3 cli.py endstep find PlayerOne --season <season-id>
```

Команда только читает текущий Pauper-лидерборд, дополнительно проверяет точное
регистронезависимое совпадение ника и показывает место на сайте, rating, RD и
W–L–D. Если игрок ещё provisional, место на сайте отсутствует. Это внутренний
JSON-интерфейс собственного frontend Endstep, а не опубликованный публичный API.

### Статистика для сезонных ачивок

Read-only snapshot на начало сезона, без изменений БД и Telegram-сообщений:

```bash
python3 cli.py achievements season-stats --as-of 2026-09-01
python3 cli.py achievements season-stats --as-of 2026-09-01 --format json -o /tmp/season.json
```

По умолчанию команда строит топ-10 колод за 120 дней, head-to-head за год и сравнивает
два соседних 90-дневных окна винрейта. Подробные правила и продуктовая концепция:
[`season_achievements.md`](season_achievements.md).

### Опции

| Команда | Опция | Описание |
|---------|-------|----------|
| `delete-last` | `-y` / `--yes` | Не спрашивать подтверждение |
| `import` | `--id INT` | ID турнира (по умолчанию — активный) |
| `export-excel` | `--id INT` | ID турнира (по умолчанию — последний) |
| `export-excel` | `-o PATH` | Путь для сохранения файла |
| `swiss setup` | `--players INT` | Число фейковых игроков (2–512, по умолчанию 110) |
| `swiss setup` | `--rounds INT` | Swiss-раундов (3–20, по умолчанию 7) |
| `swiss setup` | `--playoff INT` | Размер плей-оффа: 8 или 16; 0 — без плей-оффа |
| `swiss *` | `--id INT` | ID турнира (по умолчанию — последний активный Endstep) |
| `swiss *` | `--admin-id INT` | Актор (по умолчанию `OWNER_CHAT_ID`) |

## Типичный флоу

```bash
# Сбросить состояние и прогнать полный цикл
python3 cli.py tournament delete-last -y
python3 cli.py tournament create "Pauper Friday #42"
python3 cli.py tournament import https://aetherhub.com/Tourney/RoundTourney/99291
python3 cli.py tournament export-excel -o /tmp/results.xlsx
```

## E2E тесты

Регрессионные тесты флоу: create → import → export. Используют SQLite in-memory, без сети.

```bash
python3 -m pytest tests/e2e/ -v
```

Тесты в `tests/e2e/test_tournament_flow.py`:

| Тест | Что проверяет |
|------|--------------|
| `test_create_tournament` | Создание турнира в статусе REGISTRATION |
| `test_delete_last` | Удаление последнего по дате, не затрагивает предыдущие |
| `test_import_aetherhub` | Импорт игроков, финальные места, паринги |
| `test_import_idempotent` | Повторный импорт не дублирует участников |
| `test_export_excel` | Excel генерируется и сохраняется |
| `test_full_flow` | Полный цикл end-to-end |
