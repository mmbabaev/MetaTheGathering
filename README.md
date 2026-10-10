# MetaGatherer

Telegram-бот для сбора данных о метагейме Magic: The Gathering Pauper-турниров.

Участники самостоятельно регистрируют свои архетипы колод. Сообщество валидирует записи через голосование. Администраторы экспортируют итоговую мету в CSV / Markdown.

Актуальное состояние продукта, активные эпики и открытые решения собраны в
[`TODO.md`](TODO.md). План обновляется вместе с изменениями реализации и scope.

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

### 2. Конфигурация локального Debug

Локальный `server.sh` всегда запускает только Debug-режим и читает `bot/.env.debug`:

```env
TELEGRAM_BOT_TOKEN=<токен отдельного debug-бота>
DATABASE_URL=postgresql://user:password@localhost:5432/metagatherer_debug
```

Debug-токен должен отличаться от production-токена. База должна быть локальной
(SQLite или PostgreSQL на `localhost`/`127.0.0.1`). Production `bot/.env` локально не используется.

### 3. База данных

```bash
alembic upgrade head
```

### 4. Запуск

```bash
./server.sh          # перезапустить Debug (стоп + старт) — по умолчанию
./server.sh start    # запустить Debug, если не запущен
./server.sh stop     # остановить
./server.sh status   # PID и последние 20 строк лога
./server.sh logs     # tail -f server.log
```

> **Внимание:** не запускайте `python main.py` локально с продовым токеном — это вызовет конфликт с сервером (`Conflict: terminated by other getUpdates request`). Для локальной разработки используйте отдельный тестовый токен.

### После merge PR

Перед переходом к следующему PR обновите локальную Debug-версию из `main` и убедитесь, что она
запустилась на локальной базе:

```bash
git fetch origin main
git checkout main
git pull --ff-only origin main
BOT_ENV=debug python3 -m alembic upgrade head
./server.sh restart
./server.sh status
```

`server.sh` читает только `bot/.env.debug`, проверяет локальность Debug-базы и не должен
подключаться к production.

---

## Деплой

Деплой происходит автоматически через GitHub Actions:

- push в `main` → деплой на продовый сервер, только когда repository variable
  `DEPLOY_ENABLED=true`
- открытие PR → тесты; debug-деплой также выполняется только при
  `DEPLOY_ENABLED=true`

Сейчас деплои временно приостановлены из-за недоступности дата-центра. Новые PR можно
проверять и вливать после успешных тестов, не затрагивая production. После восстановления
VM владелец может вернуть `DEPLOY_ENABLED=true` в Settings → Secrets and variables →
Actions → Variables.

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
