# Рефакторинг: устранение дублирования get_tournament_meta

> Приоритет: высокий  
> Статус: не начато

---

## Проблема

`get_tournament_meta` реализован дважды с идентичным SQL:

| Файл | Строки |
|------|--------|
| `services/stats.py` | 34–59 |
| `services/tournament.py` | 510–535 |

Дополнительно: `services/export.py:115` делает ленивый импорт `StatsService` прямо внутри метода, что сигнализирует о нечётком владении логикой.

Датакласс `MetaRow` тоже дублируется:
- `services/stats.py:12–18`
- `services/tournament.py:35–41`

---

## Целевое состояние

- Единственная реализация `get_tournament_meta` живёт в `StatsService`
- `MetaRow` и `ArchetypeItem` определены ровно в одном месте — `services/stats.py`
- `TournamentService` делегирует вызовы `StatsService` (или метод удаляется совсем)
- `ExportService` импортирует `StatsService` на уровне модуля, не внутри метода

---

## Шаги реализации

### 1. Переместить `MetaRow` в `services/stats.py`

`MetaRow` уже определён в `stats.py`. В `tournament.py:35–41` — дубль. Нужно:

```python
# services/tournament.py — удалить:
@dataclass
class MetaRow:
    archetype_id: int
    archetype_name: str
    count: int
    upvotes_sum: int
    downvotes_sum: int

# services/tournament.py — добавить импорт:
from services.stats import MetaRow  # re-export для обратной совместимости калькуляторов
```

> **Осторожно:** перед удалением проверить все импорты `MetaRow` из `tournament.py`:
> ```
> grep -r "from services.tournament import" .
> grep -r "tournament.MetaRow" .
> ```

### 2. Удалить `TournamentService.get_tournament_meta`

Метод `tournament.py:510–535` — точный дубль. Алгоритм действий:

1. Найти всех вызывающих:
   ```
   grep -r "get_tournament_meta" .
   ```
2. Для каждого вызова `svc.get_tournament_meta(...)` заменить на вызов через `StatsService`:
   ```python
   # было
   meta = self.svc.get_tournament_meta(tournament_id)

   # стало
   from services.stats import StatsService
   meta = StatsService(self.svc.db).get_tournament_meta(tournament_id)
   ```
   Либо (если StatsService уже инжектируется) — `self.stats_svc.get_tournament_meta(...)`.

3. Удалить метод из `TournamentService`.

### 3. Исправить ленивый импорт в `ExportService`

**Текущий код** (`services/export.py:110–118`):
```python
def export_meta_markdown(self, tournament_id: int) -> str:
    from services.stats import StatsService   # ← ленивый импорт внутри метода

    stats = StatsService(self.db)
    meta = stats.get_tournament_meta(tournament_id)
```

**После рефакторинга:**
```python
# services/export.py — верхний уровень файла
from services.stats import StatsService

class ExportService:
    def __init__(self, db: Session):
        self.db = db
        self._stats = StatsService(db)   # создаём один раз

    def export_meta_markdown(self, tournament_id: int) -> str:
        meta = self._stats.get_tournament_meta(tournament_id)
        ...
```

### 4. Обновить тесты

- Убедиться, что тесты `get_tournament_meta` есть в `tests/test_stats_service.py` (или создать)
- Удалить дублирующие тесты из `tests/test_tournament_service.py` если они тестируют мета-запрос
- Добавить тест `ExportService.export_meta_markdown` если его нет

---

## Чеклист

- [ ] `MetaRow` оставлен только в `services/stats.py`; из `tournament.py` удалён
- [ ] Все импорты `MetaRow` обновлены (если были из `tournament`)
- [ ] `TournamentService.get_tournament_meta` удалён
- [ ] Все вызовы `svc.get_tournament_meta()` переведены на `StatsService`
- [ ] Ленивый импорт в `export.py` заменён на модульный
- [ ] `ExportService` использует `StatsService` через `self._stats`
- [ ] Тесты проходят: `python3 -m pytest tests/ -v`

---

## Риски

- Если `TournamentService.get_tournament_meta` вызывается из Telegram-обёрток или планировщика — нужно обновить и их. Проверить `grep -r "get_tournament_meta" bot/ bot/scheduler.py`.
- `ArchetypeItem` (в `tournament.py:28–31`) понадобится при рефакторинге Issue 2 (`ArchetypeService`). Координировать вместе.
