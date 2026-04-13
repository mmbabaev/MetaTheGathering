# Session: feat/live-status — 2026-04-13

## Ветка

`feat/live-status` (от `main`)

## Что было сделано

### 1. Динамические кнопки на карточке турнира

Карточка турнира теперь показывает разные кнопки в зависимости от статуса регистрации пользователя:

- **Не зарегистрирован** → кнопка «Записаться» (`CB_REGISTER`)
- **Зарегистрирован** → кнопка «🚪 Выйти из турнира» (`CB_LEAVE`)
- **Всегда** → кнопка «📋 Статус» (`CB_TSTATUS`)

Затронутые файлы: `bot/keyboards/__init__.py`, `bot/handlers/player.py`, `bot/telegram/player.py`

### 2. Флоу выхода из турнира с подтверждением

Новые колбэки: `CB_LEAVE` → экран подтверждения → `CB_LEAVE_CONFIRM` / `CB_LEAVE_CANCEL`.

Новые методы в `PlayerHandler`: `handle_leave_tournament`, `handle_leave_confirm`.

### 3. UserService — выделен в отдельный класс

Методы работы с пользователями вынесены из `TournamentService` в `services/user.py`:

```python
class UserService:
    def get_by_tg_id(self, tg_id: int) -> Optional[models.User]
    def get_or_create(self, *, tg_id, username, first_name, last_name) -> models.User
    def update_name(self, tg_id, first_name, last_name=None) -> models.User
```

`TournamentService` больше не содержит методы `get_user_by_tg_id`, `update_user_name`, `get_or_create_user`.

### 4. Рефактор: классовые хендлеры с конструкторной инъекцией зависимостей

Все хендлеры переведены с свободных функций `handle_xxx(db, ...)` на классы с DI:

| Класс | Файл | Зависимости |
|-------|------|-------------|
| `PlayerHandler` | `bot/handlers/player.py` | `TournamentService`, `UserService` |
| `AdminHandler` | `bot/handlers/admin.py` | `TournamentService`, `UserService` |
| `SettingsHandler` | `bot/handlers/settings.py` | `UserService` |

`bot/telegram/` обёртки используют фабрики `_xxx_handler(db)`:

```python
def _player_handler(db) -> PlayerHandler:
    return PlayerHandler(TournamentService(db), UserService(db))
```

**Мотивация:** тесты теперь могут подменять зависимости через конструктор — настоящая изоляция без implicit service creation внутри функций.

### 5. Тесты

- 194 теста, все зелёные
- `test_player_actions.py`, `test_admin_actions.py`, `test_settings.py` обновлены: используют фикстуру `handler(svc, user_svc)` вместо вызовов свободных функций
- Добавлены тесты для `handle_leave_tournament`, `handle_leave_confirm`, динамических кнопок, `handle_tournament_public_status`

## Коммиты в ветке

```
b14f5f9 refactor: class-based handlers with constructor DI
99e03e8 feat: dynamic tournament card buttons + UserService refactor
```

## Обсуждение: моки vs real services в тестах

Текущий подход — real services с SQLite in-memory. Сознательный выбор:

- SQLite in-memory быстрый (~1ms на тест) и даёт реальную схему
- Сервисы покрыты отдельно в `test_tournament_service.py`
- Меньше boilerplate, больше реализма

Конструкторная инъекция даёт **опцию** использовать моки там где нужна точечная изоляция:

```python
svc = Mock()
svc.register_participant.side_effect = ParticipantAlreadyRegistered
handler = PlayerHandler(svc, Mock())
result = handler.handle_archetype(...)
assert result.is_alert
```
