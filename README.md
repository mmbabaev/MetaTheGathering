# MetaGatherer

Telegram-бот для сбора данных о метагейме Magic: The Gathering Pauper-турниров.

Участники самостоятельно регистрируют свои архетипы колод. Сообщество валидирует записи через голосование. Администраторы экспортируют итоговую мету в CSV / Markdown.

---

## Стек

- Python 3.11+
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) 21.x
- SQLAlchemy 2.x + Alembic (PostgreSQL в проде, SQLite в тестах)
- Pydantic v2
- FastAPI + Jinja2 (веб-панель)

---

## Быстрый старт

### 1. Зависимости

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Конфигурация

Создайте `.env` в корне проекта:

```env
TELEGRAM_BOT_TOKEN=<токен бота>
DATABASE_URL=postgresql://user:password@localhost:5432/metagatherer
```

### 3. База данных

```bash
alembic upgrade head
```

### 4. Запуск

```bash
./server.sh          # перезапустить (стоп + старт) — по умолчанию
./server.sh start    # запустить, если не запущен
./server.sh stop     # остановить
./server.sh status   # PID и последние 20 строк лога
./server.sh logs     # tail -f server.log
```

> **Внимание:** не запускайте `python main.py` локально с продовым токеном — это вызовет конфликт с сервером (`Conflict: terminated by other getUpdates request`). Для локальной разработки используйте отдельный тестовый токен.

---

## Деплой

Деплой происходит автоматически через GitHub Actions:

- push в `main` → деплой на продовый сервер
- открытие PR → деплой на дебаг-сервер

---

## Тесты

```bash
# Все тесты
python -m pytest tests/

# С отчётом покрытия
python -m pytest tests/ --cov=. --cov-report=term-missing --ignore=.venv

# Один файл
python -m pytest tests/test_tournament_service.py -v
```

181 тест, ~84% покрытия. Тесты используют SQLite in-memory — PostgreSQL не нужен.

---

## Архитектура

```
main.py  →  bot/telegram/  →  bot/handlers/  →  services/  →  core/models + database
```

| Слой | Описание |
|---|---|
| `bot/telegram/` | Тонкие async-обёртки над Telegram API; не тестируются |
| `bot/handlers/` | Чистая бизнес-логика; принимают примитивы + Session, возвращают `HandlerResult` |
| `services/` | Сервисный слой; основной класс — `TournamentService` |
| `core/` | ORM-модели (SQLAlchemy), Pydantic-схемы, фабрика сессий |

### Состояния турнира

`REGISTRATION → ONGOING → VOTING → CLOSED`

### Правила голосования

- `upvotes − downvotes ≥ 3` → архетип подтверждён
- `downvotes − upvotes ≥ 3` → архетип отклонён
- Cooldown между сменой голоса: 30 секунд
- Голосование за себя запрещено
