# Рефакторинг: устранение дублирования _is_admin

> Приоритет: высокий  
> Статус: не начато

---

## Проблема

Метод `_is_admin(tg_id: int) -> bool` определён дважды с идентичной реализацией:

```python
# bot/handlers/player.py:37–41
def _is_admin(self, tg_id: int) -> bool:
    if tg_id in settings.admin_ids:
        return True
    user = self.user_svc.get_by_tg_id(tg_id)
    return user is not None and (user.is_admin or user.is_superadmin)

# bot/handlers/admin.py:94–98  — идентично
def _is_admin(self, tg_id: int) -> bool:
    if tg_id in settings.admin_ids:
        return True
    user = self.user_svc.get_by_tg_id(tg_id)
    return user is not None and (user.is_admin or user.is_superadmin)
```

Проблемы:
- Если логика проверки прав изменится (например, добавится роль `moderator`) — нужно менять в двух местах
- Логика проверки прав по содержанию принадлежит `UserService`, а не хендлерам

---

## Целевое состояние

Метод `is_admin(tg_id: int) -> bool` живёт в `UserService`. Хендлеры вызывают `self.user_svc.is_admin(tg_id)`.

Приватные `_is_admin` из обоих хендлеров удаляются.

---

## Шаги реализации

### 1. Добавить `UserService.is_admin`

```python
# services/user.py
from core.config import settings   # добавить импорт

class UserService:
    ...

    def is_admin(self, tg_id: int) -> bool:
        """Проверить, является ли пользователь администратором.

        Порядок проверки:
        1. tg_id входит в settings.admin_ids (конфигурационные суперадмины)
        2. В БД у пользователя is_admin=True или is_superadmin=True
        """
        if tg_id in settings.admin_ids:
            return True
        user = self.get_by_tg_id(tg_id)
        return user is not None and (user.is_admin or user.is_superadmin)
```

> `get_by_tg_id` уже есть в `UserService` — новый метод просто использует его.

### 2. Обновить `bot/handlers/player.py`

Удалить метод `_is_admin` (строки 37–41).

Заменить все вызовы `self._is_admin(tg_id)` на `self.user_svc.is_admin(tg_id)`.

Затронутые места в `player.py`:
- `_tournament_card` (строка ~50): `is_admin = self._is_admin(tg_id)`

```python
# было
is_admin = self._is_admin(tg_id)

# стало
is_admin = self.user_svc.is_admin(tg_id)
```

### 3. Обновить `bot/handlers/admin.py`

Удалить метод `_is_admin` (строки 94–98).

Заменить все вызовы `self._is_admin(tg_id)` на `self.user_svc.is_admin(tg_id)`.

Затронутые места в `admin.py`:
- `handle_add_me` (строка ~117)
- `handle_add_player` (строка ~158)
- `handle_add_players` (строка ~195)
- `handle_bulk_add_by_name` (строка ~236)
- `handle_tournament_status` (строка ~272)
- `handle_close_tournament` (строка ~284)

```python
# было
if not self._is_admin(tg_id):
    return HandlerResult(NOT_ADMIN)

# стало
if not self.user_svc.is_admin(tg_id):
    return HandlerResult(NOT_ADMIN)
```

### 4. Обновить тесты

Добавить тест-кейсы для `UserService.is_admin` в `tests/test_user_service.py` (или создать файл):

```python
# tests/test_user_service.py

def test_is_admin_via_settings(user_svc, monkeypatch):
    """tg_id из settings.admin_ids → True без обращения к БД."""
    monkeypatch.setattr(settings, "admin_ids", {999})
    assert user_svc.is_admin(999) is True

def test_is_admin_via_db_flag(user_svc, db):
    """user.is_admin=True в БД → True."""
    user = models.User(tg_id=42, is_admin=True)
    db.add(user)
    db.commit()
    assert user_svc.is_admin(42) is True

def test_is_superadmin_via_db_flag(user_svc, db):
    """user.is_superadmin=True в БД → True."""
    user = models.User(tg_id=43, is_superadmin=True)
    db.add(user)
    db.commit()
    assert user_svc.is_admin(43) is True

def test_is_admin_unknown_user(user_svc):
    """Неизвестный tg_id → False."""
    assert user_svc.is_admin(99999) is False

def test_is_admin_regular_user(user_svc, db):
    """Обычный пользователь (is_admin=False) → False."""
    user = models.User(tg_id=55, is_admin=False, is_superadmin=False)
    db.add(user)
    db.commit()
    assert user_svc.is_admin(55) is False
```

Убедиться, что существующие тесты хендлеров, проверяющие поведение «не-админ», по-прежнему проходят без изменений (они тестируют поведение хендлера, а не реализацию метода).

---

## Порядок выполнения

```
1. Добавить UserService.is_admin — services/user.py
2. Заменить self._is_admin → self.user_svc.is_admin в player.py
3. Заменить self._is_admin → self.user_svc.is_admin в admin.py
4. Удалить приватные _is_admin из обоих хендлеров
5. Добавить тесты UserService.is_admin
6. python3 -m pytest tests/ -v
```

---

## Чеклист

- [ ] `UserService.is_admin(tg_id: int) -> bool` добавлен
- [ ] `_is_admin` удалён из `PlayerHandler`
- [ ] `_is_admin` удалён из `AdminHandler`
- [ ] Все вызовы обновлены на `self.user_svc.is_admin(tg_id)`
- [ ] Тесты для `UserService.is_admin` написаны
- [ ] `python3 -m pytest tests/ -v` — все тесты зелёные

---

## Замечания

- Импорт `settings` в `user.py` создаёт зависимость `UserService → core.config`. Это нормально — `UserService` уже косвенно зависит от конфига через остальные части приложения.
- Если в будущем потребуется более сложная RBAC-система (роли, разрешения), метод `is_admin` можно вынести в отдельный `AuthService` без изменения интерфейса хендлеров.
