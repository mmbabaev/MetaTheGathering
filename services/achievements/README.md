# Achievement system: карта кода и текущее состояние

Эта папка содержит **lifetime-движок ачивок**, который считает достижения по уже
импортированным турнирам. Перед изменениями также прочитайте
глобальный [план проекта](../../TODO.md), подробный lifetime design в
[`docs/achievements.md`](../../docs/achievements.md) и правила безопасности в
[`CLAUDE.md`](../../CLAUDE.md). Если реализация меняет status, зависимости или
продуктовое решение, обновите `TODO.md` в том же PR.

## Что уже работает

На 18 августа 2026 года в текущем коде есть:

- 7 механик / 20 уровней: `debut`, `first_deck`, `undefeated`, `scribe`,
  `regular`, `multiclass`, `loyalist`;
- идемпотентная выдача lifetime-ачивок и snapshots текущего прогресса;
- backfill, audit и owner-only `/achievements`;
- DB lease, processing runs и transactional outbox для owner-отчёта;
- повторная доставка недоставленных частей отчёта без дублей.
- explicit gates `self_registered`, `actually_played`, `tournament_closed`,
  `result_complete` на каждом rule и read-only canonical match projection;
- immutable progress events с evidence/source/version и idempotent replay;
- универсальный owner/player outbox с versioned targeted payload, opt-in и allow-list.
- read-only локальный snapshot сезонной статистики и pure bingo generator 4×4 с
  versioned preview-каталогом для четырёх fairness-personas;
- owner/admin `/bingo_preview`, который отвечает только инициатору и не создаёт
  production boards.

Движок работает в **owner-only shadow mode**. Игрокам ничего автоматически не
рассылается. Сезоны, персональное bingo-поле 4×4, клетки, prize claims и полный
Board Lab с реальными игроками ещё не существуют.

Локальный snapshot не является внешним stats API или сезонной моделью, а preview-каталог
не создаёт production boards. Для запуска по-прежнему нужны Season/Board/Cell persistence,
immutable completion events и утверждённый ruleset.

## Поток обработки турнира

```text
завершённый импорт турнира
  -> bot/telegram/achievements.send_achievements_report
  -> DB lease на tournament_id
  -> retry существующего owner outbox ИЛИ AchievementService.process_tournament
  -> TournamentContext + проверка полноты результатов
  -> независимые rules
  -> awards + progress snapshots/events + processing run + owner/player outbox
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
| `context.py` | Независимые data requirements, eligibility и причины skip |
| `history.py` | Read-only canonical matches и только закрытая/полная история реально сыгравших |
| `service.py` | Evaluate/apply, awards, progress, processing run, shelf и backfill |
| `report.py` | Формирование текстового owner-отчёта |
| `bingo/models.py` | Versioned manifest/candidate/BoardDraft contracts без DB |
| `bingo/generator.py` | Детерминированный constraint solver поля 4×4 |
| `bingo/fixtures.py` | Preview-pool и четыре fairness-personas для Board Lab |
| `bingo/parameterizers.py` | Pure-параметризация и проверка конкретных сезонных candidates |
| `../achievement_bingo_image.py` | PNG 4×4 для owner/admin preview-команды |
| `__init__.py` | Публичные импорты модуля |

Соседние точки интеграции:

- `bot/telegram/achievements.py` — команда, оркестрация расчёта и единственная
  текущая маршрутизация получателя;
- `bot/handlers/bingo.py`, `bot/telegram/bingo.py` — read-only `/bingo_preview` для
  одного owner/admin-инициатора, без рассылок и production writes;
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
- `AchievementProgressEvent` — immutable before/after, evidence, sources и versions.
- `AchievementReportDelivery` — универсальный outbox owner/player/targeted payload.
- `AchievementProcessingLease` — временная блокировка обработки турнира.
- `AchievementProcessingRun` — итог запуска и ошибки отдельных rules.

Preview-контракты и pure generator bingo лежат отдельно в `bingo/`; подробный контракт —
[`docs/achievement_bingo_generator.md`](../../docs/achievement_bingo_generator.md). Они не
создают production Season/Board/Cell и не меняют lifetime awards.

Season/Board/Cell, сезонные progress/completion events, peer confirmations и prize claims
должны получить отдельные DB-модели. Не добавляйте сезонную семантику в lifetime awards
как скрытые поля.

## Инварианты и известные пробелы

1. Счётчики пересчитываются из первичных данных. Нельзя хранить `+1` как единственный
   источник правды.
2. Повторный и параллельный запуск не должен дублировать award, progress event или
   доставку.
3. `evaluate_for_tournament()` read-only: name resolver не создаёт и не merge пользователей.
4. Каждое rule явно объявляет четыре gates; исторические counters читают только
   `actually_played + tournament_closed + result_complete`.
5. Player delivery реализована, но выключена по умолчанию. Отправка требует global
   flag + per-user opt-in + `notify_allowed_ids`; debug отправляет только инициатору.
6. `general_name` — стабильный ключ архетипа для статистики; `name` — отображаемый
   вариант. Не группируйте колоды по display name без явной причины.
7. Сезонная `play_deck` замораживает одну конкретную `general_name` и id stats snapshot:
   несколько вариантов могут войти в candidate pool, но solver оставляет на поле не больше
   одной клетки этой mechanic. Fixture-каталог v4 использует все десять архетипов
   актуального годового production snapshot с ручными названиями; production season
   должен заморозить собственный snapshot на дату старта.
8. `/bingo_preview` работает только на fixtures, принимает persona/seed и всегда отвечает
   в тот же private chat. Это визуальный preview, а не activation или player board.
9. Накопительная `play_deck` версии 2 замораживает цель в три разных турнира и считает
   progress replay первичных фактов после `board.activated_at`. Все eligibility-gates
   обязательны; повтор одного `tournament_id` не увеличивает counter. Binary v1 остаётся
   отдельным контрактом для воспроизводимости уже созданных preview.

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
  eligibility, delivery и audit (7/7, закрывается этим изменением);
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
