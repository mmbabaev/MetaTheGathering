# Achievement system: карта кода и текущее состояние

Эта папка содержит **lifetime-движок ачивок**, который считает достижения по уже
импортированным турнирам. Перед изменениями также прочитайте
глобальный [план проекта](../../TODO.md), подробный lifetime design в
[`docs/achievements.md`](../../docs/achievements.md) и правила безопасности в
[`CLAUDE.md`](../../CLAUDE.md). Если реализация меняет status, зависимости или
продуктовое решение, обновите `TODO.md` в том же PR.

## Что уже работает

На 9 августа 2026 года в `main` есть:

- 7 механик / 20 уровней: `debut`, `first_deck`, `undefeated`, `scribe`,
  `regular`, `multiclass`, `loyalist`;
- идемпотентная выдача lifetime-ачивок и snapshots текущего прогресса;
- backfill, audit и owner-only `/achievements`;
- DB lease, processing runs и transactional outbox для owner-отчёта;
- повторная доставка недоставленных частей отчёта без дублей.

Движок работает в **owner-only shadow mode**. Игрокам ничего автоматически не
рассылается. Сезоны, персональное bingo-поле 4×4, клетки, prize claims и Board Lab
ещё не существуют в `main`.

PR [#210](https://github.com/mmbabaev/MetaTheGathering/pull/210) добавляет read-only
локальный snapshot сезонной статистики, но это не внешний stats API и не сезонная
модель. До merge код PR нельзя считать частью `main`.

## Поток обработки турнира

```text
завершённый импорт турнира
  -> bot/telegram/achievements.send_achievements_report
  -> DB lease на tournament_id
  -> retry существующего owner outbox ИЛИ AchievementService.process_tournament
  -> TournamentContext + проверка полноты результатов
  -> независимые rules
  -> awards + progress snapshots + processing run + owner outbox
     в одной транзакции
  -> последовательная доставка owner-отчёта с retry
```

Правило не должно импортировать Telegram, отправлять сообщения или самостоятельно
делать `commit`. Оно читает `TournamentContext`/`AchievementHistory` и возвращает
`Award`/`ProgressUpdate`. Запись и идемпотентность принадлежат сервису.

## Что где лежит

| Файл | Ответственность |
|---|---|
| `definitions.py` | Коды, названия, уровни, thresholds и порядок показа — source of truth каталога в коде |
| `registry.py` | Проверка согласованности definitions, rules и порядка кодов |
| `rules.py` | Pure business rules и `default_rules()` |
| `context.py` | Контекст одного турнира, текущий eligibility и причины skip |
| `history.py` | Кэшированная история участий, парингов, результатов и колод |
| `service.py` | Evaluate/apply, awards, progress, processing run, shelf и backfill |
| `report.py` | Формирование текстового owner-отчёта |
| `__init__.py` | Публичные импорты модуля |

Соседние точки интеграции:

- `bot/telegram/achievements.py` — команда, оркестрация расчёта и единственная
  текущая маршрутизация получателя;
- `bot/handlers/achievements.py` — Telegram-независимая логика shelf;
- `services/achievement_delivery.py` — owner text outbox;
- `services/achievement_processing_lease.py` — межпроцессный lock турнира;
- `services/achievement_report_log.py` — best-effort forensic JSON log;
- `services/achievement_image.py` — PNG-карточки и shelf;
- `cli/achievements.py` — process/show/audit/backfill/list;
- `core/models.py` — таблицы awards, progress, deliveries, lease и processing runs;
- `tests/test_achievements_*.py`, `tests/test_achievement_*.py` — основной контракт.

## Модель данных сейчас

- `UserAchievement` — неизменяемый факт lifetime-награды. Уникальность
  `(user_id, code, level)` обеспечивает идемпотентность.
- `UserAchievementProgress` — только последний вычисленный snapshot счётчика, не
  история изменений.
- `AchievementReportDelivery` — outbox частей owner-отчёта.
- `AchievementProcessingLease` — временная блокировка обработки турнира.
- `AchievementProcessingRun` — итог запуска и ошибки отдельных rules.

Season/Board/Cell, immutable progress events, peer confirmations и prize claims
должны получить отдельные модели. Не добавляйте сезонную семантику в lifetime awards
как скрытые поля.

## Инварианты и известные пробелы

1. Счётчики пересчитываются из первичных данных. Нельзя хранить `+1` как единственный
   источник правды.
2. Повторный и параллельный запуск не должен дублировать award, progress event или
   доставку.
3. `evaluate_for_tournament()` задуман read-only. Текущий name resolver использует
   импортный resolver, который может объединять пользователей; это известный пробел
   [#212](https://github.com/mmbabaev/MetaTheGathering/issues/212), его нельзя
   распространять на новые read-only сценарии.
4. Текущий eligibility в основном означает «сам записал колоду». Это ещё не строгое
   `actually_played + tournament_closed + result_complete`: no-show и исторически
   неполные турниры требуют исправления в #199/#212.
5. Автоматическая player delivery не реализована. Любой новый цикл
   `bot.send_message` по игрокам требует отдельного подтверждения и должен соблюдать
   `notify_allowed_ids`. Debug отправляет сообщение только инициатору.
6. `general_name` — стабильный ключ архетипа для статистики; `name` — отображаемый
   вариант. Не группируйте колоды по display name без явной причины.

## Как добавить lifetime-rule

1. Добавить code и definitions в `definitions.py`, включая место в `CODE_ORDER`.
2. Реализовать rule в `rules.py` и включить его в `default_rules()`.
3. Получать данные через context/history; не делать Telegram-вызовов и скрытых writes.
4. Сформировать короткий `evidence`, достаточный для owner-аудита.
5. Добавить positive, negative, boundary и repeated-run/idempotency tests.
6. Проверить registry и полный набор achievement-тестов:

```bash
python3 -m pytest tests/test_achievements_registry.py \
  tests/test_achievements_rules.py \
  tests/test_achievements_service.py -q
```

## Карта задач

- [#167](https://github.com/mmbabaev/MetaTheGathering/issues/167) — общий индекс и
  фактический статус;
- [#199](https://github.com/mmbabaev/MetaTheGathering/issues/199) — hardening
  eligibility, delivery и audit;
- [#200](https://github.com/mmbabaev/MetaTheGathering/issues/200) — каталог идей;
- [#211](https://github.com/mmbabaev/MetaTheGathering/issues/211) — внешний stats API;
- [#212](https://github.com/mmbabaev/MetaTheGathering/issues/212) — сезонная архитектура;
- [#213](https://github.com/mmbabaev/MetaTheGathering/issues/213) — generator и Board Lab;
- [#214](https://github.com/mmbabaev/MetaTheGathering/issues/214) — peer confirmations;
- [#215](https://github.com/mmbabaev/MetaTheGathering/issues/215) — правила конкурса;
- [#216](https://github.com/mmbabaev/MetaTheGathering/issues/216) — метрики и fairness.

Если README, roadmap и issue расходятся с кодом, код и миграции описывают уже
поставленное поведение. После сверки обновите `TODO.md` и #167, чтобы roadmap и
продуктовый индекс снова отражали фактическое состояние.
