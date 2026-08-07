---
name: improve-deck-archetypes
description: Update MetaGatherer deck-classification logic from a real tournament and add a complete regression test set for that tournament without replacing player-entered archetypes. Use when the user asks after an event to fetch its decks, improve raw name → general_name/macro_name mapping, handle spelling variants or colors, encode accepted rules, test every real deck name, and publish the changes in a PR.
---

# Improve Deck Archetypes

После каждого выбранного турнира выполнять две обязательные задачи: обновлять логику классификации по подтверждённым реальным кейсам и добавлять полный тестовый набор этого турнира.

Перед работой прочитать:

- [references/project-map.md](references/project-map.md) — источники данных и ключевые файлы;
- [references/classification-rules.md](references/classification-rules.md) — уже принятые правила и пороги.

## Workflow

1. Определить точный турнир по ID, названию или AetherHub URL. Не подменять его похожим событием.
2. Получить read-only срез фактических участников и колод: исходное имя, `general_name`, `macro_name`, `color_identity`, место и число использований. Производственные секреты читать только внутри сервера из `bot/.env`; не выводить их.
3. Построить таблицу `исходное → текущее general/macro → предлагаемое`, найти необработанные варианты и применить уже подтверждённые владельцем решения. Не завершать работу одним отчётом: если правило определено, изменить код.
4. Выбрать правильный слой изменения:
   - исходный свободный ввод всегда сохранять в `Archetype.name` через `services/archetype.py`;
   - каноническое название, цветовой префикс или синоним по правилам пунктов 1–2 → `services/deck_mapping.py` и отдельный `general_name`;
   - строгий fuzzy для конкретного канонического типа → отдельный `general_name`;
   - объединение в крупную стратегическую семью и его fuzzy → `macro_name` и `macro_archetype()`;
   - подтверждённый цвет → `services/deck_book.py`; эвристический цвет → `services/deck_colors.py`;
   - owner-only диагностическая отбивка → `bot/scheduler.py`.
5. Не менять `Participant.archetype_id` и `Archetype.name` ради классификации. `general_name` хранит конкретную каноническую стратегию и значимые цветовые варианты, `macro_name` отдельно объединяет их в крупную семью.
6. Для новой колонки создать Alembic revision с уникальным UUID и одним текущим `down_revision`. Для изменения правил предусмотреть исправление старого кэша через миграцию или безопасный пересчёт.
7. Сохранить полный фактический список названий выбранного турнира как отдельный именованный параметризованный тест. Для каждой строки проверять как минимум `raw name → general_name`; когда macro включён в задачу, также проверять `raw/general → macro_name`. Не заменять этот набор синтетическими примерами.
8. Добавить отдельные юнит-тесты на новые правила и защитные негативные fuzzy-кейсы. Проверить неизменность `Archetype.name`, `Participant.archetype_id` и остальных старых полей; owner-only текст тестировать отдельно от клубного.
9. Запустить профильные тесты, `ruff check` для изменённых файлов, `git diff --check`, один Alembic head и полный `pytest tests/`.
10. При долговечном новом решении обновить [references/classification-rules.md](references/classification-rules.md) в том же PR. Так навык накапливает решения следующих турниров.
11. Для кода использовать свежую ветку от `origin/main`; продолжать существующую ветку можно только для той же задачи и только после проверки, что PR всё ещё `OPEN`. Открыть draft PR, но никогда не merge-ить его.

## Safety

- Не менять production DB вручную без прямого запроса. Нормальный путь — код, миграция, PR и штатный deploy.
- Не отправлять сообщения участникам при аудите. Тестовая диагностика допустима только owner и не должна создавать массовую рассылку.
- Не запускать локально polling с production Telegram token.
- Никогда не подменять пользовательский custom-архетип существующим архетипом через fuzzy. Fuzzy может заполнять только отдельные `general_name`/`macro_name`; при сомнении оставлять соответствующее поле пустым.

## Result

В финале дать:

- ссылку/ID турнира и разобранные исходные колоды;
- перечень реально изменённой логики с примерами;
- полный добавленный набор турнирных кейсов и результат тестов;
- ссылку на PR и оставшиеся неоднозначные названия.
