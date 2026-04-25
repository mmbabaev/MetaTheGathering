# Архитектурное ревью MetaGatherer

> Дата ревью: 2026-04-14

---

## Что сделано хорошо

- **Разделение слоёв `bot/handlers/` vs `bot/telegram/`** — чистый контракт через `HandlerResult`; handlers тестируются без Telegram-зависимостей
- **Иерархия ошибок** — `services/services_errors.py` полная, хорошо типизирована
- **ORM-модели** — enum-статусы, каскады, `utc_now()` для консистентных таймстампов
- **Тестовая инфраструктура** — SQLite in-memory, реальные сервисы без моков, 181 тест (~84% coverage)

---

## Проблемы и план устранения

### Высокий приоритет — блокирует поддержку

#### 1. Дублирование логики мета-запросов
> Детальный план: [docs/refactor_meta_query_dedup.md](refactor_meta_query_dedup.md)

- [x] Убрать дубликат `get_tournament_meta` из `services/tournament.py:510-535` — оставить единственную реализацию в `services/stats.py`
- [x] Убрать дубликат `MetaRow` из `services/tournament.py:35-41` — оставить в `services/stats.py`
- [x] Убрать ленивый импорт `from services.stats import StatsService` внутри метода в `services/export.py:115` — сделать обычный import на уровне модуля

#### 2. TournamentService нарушает SRP (`services/tournament.py`, 536 строк)
> Детальный план: [docs/refactor_archetype_service.md](refactor_archetype_service.md)

- [x] Выделить `ArchetypeService` в `services/archetype.py` — вынести `list_archetypes`, `list_archetypes_for_user`, `get_or_create_archetype_by_name`, `ArchetypeItem`
- [x] `PlayerHandler` и `AdminHandler` получают `ArchetypeService` через DI-конструктор
- [x] Обновить фабрики в `bot/telegram/player.py` и `bot/telegram/admin.py`
- [x] Написать `tests/test_archetype_service.py`

#### 3. Дублирование `_is_admin`
> Детальный план: [docs/refactor_is_admin.md](refactor_is_admin.md)

- [x] Метод `_is_admin` дублируется в `bot/handlers/player.py:37-41` и `bot/handlers/admin.py:94-98`
- [x] Добавить `UserService.is_admin(tg_id: int) -> bool`
- [x] Удалить `_is_admin` из обоих хендлеров, заменить вызовы на `self.user_svc.is_admin(tg_id)`
- [x] Написать тесты для `UserService.is_admin`

---

### Средний приоритет — ухудшает DX

#### 4. Бойлерплейт в Telegram-обёртках
- [ ] Каждый callback в `bot/telegram/` повторяет ~20 строк: открытие сессии, парсинг `query.data`, `try/finally`, отправку ответа
- [ ] Написать декоратор `@callback_handler(parser)` или контекст-менеджер `async with get_db_session() as db` в `bot/telegram/session.py`

#### 5. Разбросанный state management *(частично сделано)*
- [x] Роутинг через последовательные `if key in user_data` — разделён на `_handle_pending_*` функции (`refactor/text-input-router`)
- [ ] `bot/telegram/player.py` — 5 строковых ключей `USER_DATA_PENDING_*` без реестра
- [ ] Ввести `enum PendingStateType` + датакласс `PendingState` в `bot/telegram/state.py`; диспетчеризация через `match state.type`

#### 6. Неполная обработка ошибок в handlers
- [ ] `bot/handlers/admin.py` ловит часть исключений, но `TournamentNotFound` может улететь выше
- [ ] Создать словарь `SERVICE_ERROR_MESSAGES` и хелпер `safe_service_call()` в `bot/handlers/utils.py`

#### 7. Неформализованный state machine турнира
- [ ] `open_registration()` не проверяет допустимые переходы; правила разбросаны по методам
- [ ] Ввести таблицу `VALID_TRANSITIONS: dict[TournamentStatus, set[TournamentStatus]]` и единый метод `transition_tournament()` в `TournamentService`

---

### Низкий приоритет — полировка

#### 8. Cooldown обходится через параметр в тестах
- [ ] `cast_vote(apply_cooldown=False)` — продакшн-логика обходится вместо мока времени
- [ ] Заменить на `freezegun` в тестах; убрать параметр `apply_cooldown`

#### 9. Placeholder `tg_id` в `UserService`
- [ ] `services/user.py:66` создаёт пользователей с отрицательным `tg_id` при bulk-add
- [ ] Если реальный игрок пишет `/start` — создаётся дубликат без связи со старым
- [ ] Добавить `UserService.update_user_tg_id(user_id, real_tg_id)` и логику в `cmd_start` для обнаружения placeholder-пользователей

#### 10. Пороги голосования захардкожены
- [ ] `CONFIRM_THRESHOLD = 3` и `REJECT_THRESHOLD = 3` в `services/tournament.py:22-25`
- [ ] Перенести в `core/config.py` как `Settings.CONFIRM_THRESHOLD` и `Settings.REJECT_THRESHOLD`

---

## Неиспользуемый / мёртвый код

| Файл | Ситуация | Действие |
|------|----------|----------|
| `bot/handlers/voting.py` | Пустой; сервис `cast_vote` реализован, хендлеры — нет | [ ] Реализовать в рамках Phase 4 |
| `core/models.py` — `ArchetypeAlias` | Модель есть, ни одного вызова в сервисах | [ ] Подключить в `ArchetypeService` при реализации fuzzy-поиска |
| `utils/formatters.py` | Заглушка | [ ] Реализовать или удалить |
| `utils/validators.py` | Заглушка | [ ] Реализовать или удалить |

---

## Файлы с наибольшим техдолгом

| Файл | Строк | Проблемы |
|------|-------|---------|
| `services/tournament.py` | 536 | Дублирование мета-запроса, нарушение SRP, захардкоженные константы |
| `bot/telegram/player.py` | ~200 | Бойлерплейт, разбросанный state |
| `bot/telegram/admin.py` | 167 | Бойлерплейт, неполный error handling |
| `services/user.py` | 93 | Идемпотентность placeholder-пользователей |
