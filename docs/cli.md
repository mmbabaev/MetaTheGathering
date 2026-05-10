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
```

### Опции

| Команда | Опция | Описание |
|---------|-------|----------|
| `delete-last` | `-y` / `--yes` | Не спрашивать подтверждение |
| `import` | `--id INT` | ID турнира (по умолчанию — активный) |
| `export-excel` | `--id INT` | ID турнира (по умолчанию — последний) |
| `export-excel` | `-o PATH` | Путь для сохранения файла |

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
