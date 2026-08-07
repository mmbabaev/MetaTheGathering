# Карта классификации колод

## Источники данных

Основной источник факта — production PostgreSQL MetaGatherer. Выполнять запрос на сервере через проектный Python/SQLAlchemy, чтобы соединение читалось из `bot/.env` внутри сервера. Возвращать только турнирные данные, никогда не строку подключения.

Для выбранного `Tournament.id` читать:

- `Tournament`: `id`, `title`, `aetherhub_url`, `status`;
- `Participant`: `final_place`, `archetype_id`, `user_id`;
- `User`: имя/фамилию/username только для проверки конкретного турнира;
- `Archetype`: `name`, `general_name`, `macro_name`, `color_identity`, `is_custom`;
- `RoundPairing`: при проверке, действительно ли игрок участвовал;
- AetherHub standings/rounds через уже сохранённый URL, если нужно сверить внешний источник.

Сначала вывести агрегат по уникальным названиям и количеству, затем строки участников. Не выполнять UPDATE/DELETE во время аудита.

## Слои и файлы

- `core/models.py` — колонки `Archetype` и связи.
- `services/archetype.py` — сохранение свободного пользовательского ввода как отдельного архетипа; классификация не должна подменять его ID.
- `services/deck_mapping.py` — `general_archetype()`, `macro_archetype()` и пересчёт кэша.
- `services/deck_book.py` — подтверждённые названия, алиасы и цвета; источник истины сильнее эвристик.
- `services/deck_colors.py` — эвристическое определение WUBRG и кэш `color_identity`.
- `services/meta_chart.py` — группировка и отображение метагейма.
- `services/export.py` — выгрузка `general_name`.
- `services/archetype.py` и `services/meta_table_import.py` — создание архетипов из ручного ввода и импорта.
- `bot/scheduler.py` — финальная отбивка и экспериментальный owner-only отчёт.
- `alembic/versions/` — backfill существующего кэша.

## Тесты

- `tests/test_deck_mapping.py` — исходное имя → general/macro.
- `tests/test_archetype_menu.py` — исходный custom остаётся отдельным, а general/macro заполняются независимо.
- `tests/test_player_actions.py` — пользовательский ввод → собственный `Participant.archetype_id` плюс отдельные поля классификации.
- `tests/test_deck_colors.py` — WUBRG.
- `tests/test_meta_gather_completed.py` — owner-only финальный срез и отсутствие блока в клубном чате.
- `tests/test_migrations.py` — единственная валидная цепочка миграций.

## Проверки

```bash
python3 -m pytest tests/test_deck_mapping.py tests/test_archetype_menu.py tests/test_player_actions.py tests/test_deck_colors.py tests/test_meta_gather_completed.py tests/test_migrations.py -q
ruff check <изменённые Python-файлы>
git diff --check
DATABASE_URL="sqlite:///:memory:" python3 -m alembic heads
python3 -m pytest tests/ -q
```
