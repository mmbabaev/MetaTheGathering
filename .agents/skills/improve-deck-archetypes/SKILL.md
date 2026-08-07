---
name: improve-deck-archetypes
description: Audit and improve MetaGatherer deck-name classification after a tournament. Use when the user asks to obtain a tournament's decks, inspect how player-entered names become Archetype.name/general_name/macro_name, merge spelling variants, add fuzzy matching or aliases, correct color identities, expand macro archetypes, add owner-only diagnostics, or create tests and a PR for those changes.
---

# Improve Deck Archetypes

Проводить послетурнирный аудит всей цепочки названий колод и закреплять принятые владельцем решения в коде, миграции и регрессионных тестах.

Перед работой прочитать:

- [references/project-map.md](references/project-map.md) — источники данных и ключевые файлы;
- [references/classification-rules.md](references/classification-rules.md) — уже принятые правила и пороги.

## Workflow

1. Определить точный турнир по ID, названию или AetherHub URL. Не подменять его похожим событием.
2. Получить read-only срез фактических участников и колод: исходное имя, `general_name`, `macro_name`, `color_identity`, место и число использований. Производственные секреты читать только внутри сервера из `bot/.env`; не выводить их.
3. Показать владельцу найденные расхождения в компактном виде: `исходное → текущее → предлагаемое`, причина и уверенность. Явно принятые владельцем правила реализовывать без повторного согласования; неоднозначные слияния уточнять.
4. Выбрать правильный слой изменения:
   - опечатка свободного ввода относительно известного архетипа → `services/archetype.py`;
   - каноническое название/цветовой префикс/синоним → `services/deck_mapping.py`;
   - крупная стратегическая семья → `macro_name` и `macro_archetype()`;
   - подтверждённый цвет → `services/deck_book.py`; эвристический цвет → `services/deck_colors.py`;
   - owner-only диагностическая отбивка → `bot/scheduler.py`.
5. Не смешивать `general_name` и `macro_name`: первый сохраняет конкретную стратегию и значимые цветовые варианты, второй объединяет стратегии в крупную семью.
6. Для новой колонки создать Alembic revision с уникальным UUID и одним текущим `down_revision`. Для изменения правил предусмотреть исправление старого кэша через миграцию или безопасный пересчёт.
7. Написать юнит-тесты на каждый найденный пример и защитные негативные тесты. Обязательно проверить всю цепочку свободного ввода до `Participant.archetype_id`, а owner-only текст — отдельно от клубного.
8. Запустить профильные тесты, `ruff check` для изменённых файлов, `git diff --check`, один Alembic head и полный `pytest tests/`.
9. При долговечном новом решении обновить [references/classification-rules.md](references/classification-rules.md) в том же PR. Так навык накапливает решения следующих турниров.
10. Для кода использовать свежую ветку от `origin/main`; продолжать существующую ветку можно только для той же задачи и только после проверки, что PR всё ещё `OPEN`. Открыть draft PR, но никогда не merge-ить его.

## Safety

- Не менять production DB вручную без прямого запроса. Нормальный путь — код, миграция, PR и штатный deploy.
- Не отправлять сообщения участникам при аудите. Тестовая диагностика допустима только owner и не должна создавать массовую рассылку.
- Не запускать локально polling с production Telegram token.
- Не угадывать архетип при слабом или спорном fuzzy-совпадении. Сохранять custom-ввод либо запрашивать решение владельца.

## Result

В финале дать:

- ссылку/ID турнира и разобранные исходные колоды;
- перечень изменённых правил с примерами;
- тестовый результат;
- ссылку на PR и оставшиеся неоднозначные названия.
