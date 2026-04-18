# Рефакторинг: выделение ArchetypeService

> Приоритет: высокий  
> Статус: не начато

---

## Проблема

`TournamentService` (`services/tournament.py`, 536 строк) нарушает SRP: кроме турниров и участников он владеет операциями над архетипами. Это три метода и один датакласс:

| Элемент | Строки |
|---------|--------|
| `ArchetypeItem` (датакласс) | 28–31 |
| `list_archetypes()` | 179–183 |
| `list_archetypes_for_user()` | 185–218 |
| `get_or_create_archetype_by_name()` | 220–230 |

Проблемы текущего состояния:
- Архетипы — независимая сущность, но тесно упакованы в `TournamentService`
- В `core/models.py` есть `ArchetypeAlias` — неиспользуемая модель, которой негде жить кроме как в выделенном сервисе
- `PlayerHandler` и `AdminHandler` вызывают `svc.list_archetypes*` и `svc.get_or_create_archetype_by_name` через тот же `TournamentService`, что создаёт ненужную зависимость

---

## Целевое состояние

```
services/archetype.py  ←  новый файл
    ArchetypeService
        list_archetypes() → list[ArchetypeItem]
        list_archetypes_for_user(tg_id, total) → list[ArchetypeItem]
        get_or_create_by_name(name) → models.Archetype
```

`TournamentService` сохраняет метод `get_or_create_archetype_by_name` только там, где он нужен для internal-использования внутри `register_participant` (либо принимает готовый `archetype_id`). В остальных случаях — делегирует.

Handlers получают `ArchetypeService` через конструктор наравне с `TournamentService`.

---

## Шаги реализации

### 1. Создать `services/archetype.py`

```python
# services/archetype.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models


@dataclass
class ArchetypeItem:
    id: int
    name: str


class ArchetypeService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_archetypes(self) -> List[ArchetypeItem]:
        """Все архетипы по алфавиту."""
        stmt = select(models.Archetype).order_by(models.Archetype.name.asc())
        rows = self.db.execute(stmt).scalars().all()
        return [ArchetypeItem(id=a.id, name=a.name) for a in rows]

    def list_archetypes_for_user(self, tg_id: int, total: int = 10) -> List[ArchetypeItem]:
        """Топ-N архетипов: последние выборы пользователя первыми, остальные по алфавиту."""
        all_archetypes = self.list_archetypes()

        user_stmt = select(models.User).where(models.User.tg_id == tg_id)
        user = self.db.execute(user_stmt).scalar_one_or_none()

        recent_ids: list[int] = []
        if user:
            hist_stmt = (
                select(models.Participant.archetype_id)
                .where(
                    models.Participant.user_id == user.id,
                    models.Participant.archetype_id.isnot(None),
                )
                .order_by(models.Participant.created_at.desc())
            )
            seen: set[int] = set()
            for (aid,) in self.db.execute(hist_stmt).all():
                if aid not in seen:
                    seen.add(aid)
                    recent_ids.append(aid)

        recent_set = set(recent_ids)
        recent_map = {aid: i for i, aid in enumerate(recent_ids)}

        recent = sorted(
            [a for a in all_archetypes if a.id in recent_set],
            key=lambda a: recent_map[a.id],
        )
        rest = [a for a in all_archetypes if a.id not in recent_set]

        return (recent + rest)[:total]

    def get_or_create_by_name(self, name: str) -> models.Archetype:
        """Найти архетип по точному имени или создать новый."""
        stmt = select(models.Archetype).where(models.Archetype.name == name)
        archetype = self.db.execute(stmt).scalar_one_or_none()
        if archetype:
            return archetype
        archetype = models.Archetype(name=name.strip())
        self.db.add(archetype)
        self.db.commit()
        self.db.refresh(archetype)
        return archetype
```

### 2. Обновить `services/tournament.py`

Удалить:
- датакласс `ArchetypeItem` (строки 28–31)
- методы `list_archetypes`, `list_archetypes_for_user`, `get_or_create_archetype_by_name`

Добавить импорт для обратной совместимости внутри пакета (если нужен):
```python
from services.archetype import ArchetypeItem  # используется в MetaRow и внутри сервиса
```

> `TournamentService` сам не вызывает `get_or_create_archetype_by_name` — этот метод вызывается из `AdminHandler` и `PlayerHandler`. Значит его можно удалить из `TournamentService` без замены.

### 3. Обновить `bot/handlers/player.py`

**Было:**
```python
class PlayerHandler:
    def __init__(self, svc: TournamentService, user_svc: UserService) -> None:
        self.svc = svc
        self.user_svc = user_svc
```

**Стало:**
```python
from services.archetype import ArchetypeService

class PlayerHandler:
    def __init__(
        self,
        svc: TournamentService,
        user_svc: UserService,
        arch_svc: ArchetypeService,
    ) -> None:
        self.svc = svc
        self.user_svc = user_svc
        self.arch_svc = arch_svc
```

Обновить вызовы внутри методов:

| Было | Стало |
|------|-------|
| `self.svc.list_archetypes_for_user(tg_id)` | `self.arch_svc.list_archetypes_for_user(tg_id)` |
| `self.svc.list_archetypes()[:10]` | `self.arch_svc.list_archetypes()[:10]` |
| `self.svc.list_archetypes()` | `self.arch_svc.list_archetypes()` |
| `self.svc.get_or_create_archetype_by_name(name)` | `self.arch_svc.get_or_create_by_name(name)` |

Затронутые методы: `handle_register`, `handle_save_name_then_register`, `handle_archetype`, `handle_custom_archetype_text`.

### 4. Обновить `bot/handlers/admin.py`

Аналогично — добавить `arch_svc: ArchetypeService` в конструктор и обновить вызовы:

| Было | Стало |
|------|-------|
| `self.svc.get_or_create_archetype_by_name(deck_name)` | `self.arch_svc.get_or_create_by_name(deck_name)` |

Затронутые методы: `handle_add_me`, `handle_add_player`, `handle_add_players`.

### 5. Обновить фабрики в `bot/telegram/`

В каждом файле `bot/telegram/*.py` обновить фабричные функции:

```python
# bot/telegram/player.py
from services.archetype import ArchetypeService

def _player_handler(db) -> PlayerHandler:
    return PlayerHandler(
        TournamentService(db),
        UserService(db),
        ArchetypeService(db),
    )
```

```python
# bot/telegram/admin.py
from services.archetype import ArchetypeService

def _admin_handler(db) -> AdminHandler:
    return AdminHandler(
        TournamentService(db),
        UserService(db),
        ArchetypeService(db),
    )
```

### 6. Обновить тесты

В фикстурах `conftest.py` или файлах тестов добавить `arch_svc`:

```python
# tests/conftest.py или tests/test_player_actions.py
from services.archetype import ArchetypeService

@pytest.fixture
def arch_svc(db):
    return ArchetypeService(db)

@pytest.fixture
def player_handler(svc, user_svc, arch_svc):
    return PlayerHandler(svc, user_svc, arch_svc)

@pytest.fixture
def admin_handler(svc, user_svc, arch_svc):
    return AdminHandler(svc, user_svc, arch_svc)
```

Добавить отдельный файл тестов для `ArchetypeService`:
```
tests/test_archetype_service.py
```

Минимальные тест-кейсы:
- `test_list_archetypes_empty`
- `test_list_archetypes_sorted`
- `test_list_archetypes_for_user_recent_first`
- `test_get_or_create_by_name_creates`
- `test_get_or_create_by_name_finds_existing`

---

## Порядок выполнения

```
1. Создать services/archetype.py
2. Обновить bot/handlers/player.py
3. Обновить bot/handlers/admin.py
4. Обновить bot/telegram/player.py  (фабрика)
5. Обновить bot/telegram/admin.py   (фабрика)
6. Удалить методы из TournamentService
7. Обновить тесты — фикстуры + добавить test_archetype_service.py
8. python3 -m pytest tests/ -v
```

---

## Чеклист

- [ ] `services/archetype.py` создан с `ArchetypeService` и `ArchetypeItem`
- [ ] `ArchetypeItem` удалён из `tournament.py` (или оставлен как `from services.archetype import ArchetypeItem`)
- [ ] `list_archetypes`, `list_archetypes_for_user`, `get_or_create_archetype_by_name` удалены из `TournamentService`
- [ ] `PlayerHandler.__init__` принимает `arch_svc: ArchetypeService`
- [ ] `AdminHandler.__init__` принимает `arch_svc: ArchetypeService`
- [ ] Фабрики в `bot/telegram/player.py` и `bot/telegram/admin.py` обновлены
- [ ] Тестовые фикстуры обновлены
- [ ] `tests/test_archetype_service.py` написан
- [ ] `python3 -m pytest tests/ -v` — все тесты зелёные

---

## Задел на будущее

После выделения `ArchetypeService` в него легко добавить:
- `find_by_alias(alias: str) -> Optional[models.Archetype]` — поиск по `ArchetypeAlias` (уже есть модель в `core/models.py`)
- Fuzzy-поиск по имени (Phase 2 из TODO.md)

Эти фичи не входят в данный рефакторинг, но готовая структура их поддержит.
