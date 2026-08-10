# MetaGatherer — живой план проекта

Последнее обновление: **10 августа 2026**.

Это верхнеуровневый source of truth о том, что уже находится в `main`, что сейчас
проходит review и что ещё только запланировано. Детали и acceptance criteria живут
в связанных GitHub issues; карта кода ачивок — в
[`services/achievements/README.md`](services/achievements/README.md).

## Как поддерживать план

- Перед началом продуктовой задачи сверить этот файл, соответствующую issue и код.
- Обновлять план в том же PR, который меняет статус этапа, scope или принятое
  продуктовое решение.
- Явно различать `в main`, `в открытом PR` и `не реализовано`.
- После merge отмечать фактический результат и обновлять дату; не считать открытый
  или зелёный PR уже поставленным функционалом.
- Не переносить сюда логи работы и список использованных инструментов — только
  состояние продукта, решения, зависимости и следующий порядок действий.

## Текущий фокус: сезонные bingo-ачивки

Цель первого сезона: персональное поле 4×4 на четыре месяца, которое интересно
любителям и сильным игрокам, стимулирует самостоятельную регистрацию в боте и
использует проверяемую турнирную статистику.

### Уже в `main`

- Lifetime/shadow-движок: 7 механик / 20 definitions, идемпотентные awards и
  snapshots прогресса.
- Backfill, audit, owner-only `/achievements`, PNG shelf/cards.
- Registry validation, transactional owner outbox/retry, DB lease, processing runs
  и forensic report log.
- Карта achievement-модуля для разработчиков и агентов — source commit `90ecbf6`,
  PR [#217](https://github.com/mmbabaev/MetaTheGathering/pull/217), merge
  `49768b8`. При подготовке документации прошли 38 focused achievement tests.

Игрокам ачивки автоматически не рассылаются: текущий режим — owner-only shadow.

### В review, но ещё не в `main`

- PR [#210](https://github.com/mmbabaev/MetaTheGathering/pull/210) — read-only
  snapshot сезонной статистики из локальной БД: top decks, H2H, два окна winrate и
  quality report. PR открыт, CI и debug deploy зелёные.
- Это fallback/prototype вычислений, а не внешний stats API, Season/Board model или
  генератор поля.

### Осталось укрепить в lifetime-движке

Issue [#199](https://github.com/mmbabaev/MetaTheGathering/issues/199) закрывать
рано: выполнено **4 из 7** архитектурных этапов. Остались:

1. Явные eligibility-гейты и корректная история:
   `self_registered`, `actually_played`, `tournament_closed`, `result_complete`.
2. Immutable progress events с evidence, ruleset/stats version и replay/audit.
3. Независимая player delivery с opt-in и notification safety.

Player delivery не блокирует первый pull-only UI, но блокирует любые автоматические
сообщения игрокам.

### Ещё не реализовано

- `Season`, frozen ruleset/stats snapshot и lifecycle сезона.
- Персональные `Board`, 16 `Cell` и immutable completion/progress events.
- Pure generator поля 4×4 и проверка сложности/fairness.
- Owner Board Lab для массовой генерации и ручной валидации полей.
- Atomic row/full-board prize claims, tie review и owner approval.
- Player board UI, архив сезона и opt-in sharing.
- Peer-confirmed claims и подтверждение события реальным оппонентом.
- Внешний stats API с абсолютными окнами и стабильными player/deck IDs.

## Карта активных issues

Все перечисленные задачи открыты на дату обновления.
9 августа были актуализированы #167, #199, #200 и #211–#214; для вынесенных
продуктовых пробелов созданы #215 и #216.

| Issue | Назначение |
|---|---|
| [#167](https://github.com/mmbabaev/MetaTheGathering/issues/167) | Общий эпик и индекс системы ачивок |
| [#199](https://github.com/mmbabaev/MetaTheGathering/issues/199) | Eligibility, delivery и auditable progress текущего движка |
| [#200](https://github.com/mmbabaev/MetaTheGathering/issues/200) | Каталог существующих и будущих типов ачивок |
| [#211](https://github.com/mmbabaev/MetaTheGathering/issues/211) | Недостающие ручки внешнего API статистики |
| [#212](https://github.com/mmbabaev/MetaTheGathering/issues/212) | Сезонная архитектура, canonical Match, events и prize claims |
| [#213](https://github.com/mmbabaev/MetaTheGathering/issues/213) | Генератор bingo 4×4 и тестовый Board Lab UI |
| [#214](https://github.com/mmbabaev/MetaTheGathering/issues/214) | Peer-confirmed ачивки и state machine подтверждения |
| [#215](https://github.com/mmbabaev/MetaTheGathering/issues/215) | Правила первого сезона: сроки, cohort, late join, призы, tie, privacy, reroll и player journey |
| [#216](https://github.com/mmbabaev/MetaTheGathering/issues/216) | Baseline, funnel, fairness, мониторинг и kill switch |

## Открытые продуктовые решения

1. **Момент начала прогресса.** Рекомендация: считать только турниры после
   активации frozen board; старую статистику использовать для baseline и
   персонализации, но не закрывать ею клетки задним числом.
2. **Совмещение призов.** Может ли один игрок получить и первый приз за ряд, и
   суперприз за все 16 клеток.
3. **Late join.** До какой даты разрешать активацию поля и нужен ли отдельный cutoff
   для права на материальный приз.
4. **Tie.** Как определить победителя, если два игрока объективно закрыли ряд одним
   турниром и порядок событий нельзя доказать.
5. **Cohort.** Одна общая таблица для обоих клубов или независимые соревнования.
6. **Видимость.** Можно ли публично показывать поле до закрытия ряда; default —
   private, sharing только по явному действию игрока.

Решения должны быть зафиксированы в #215 до заморозки generator manifest и
публичной активации сезона.

## Рекомендуемый порядок реализации

1. Принять или доработать PR #210; после merge обновить этот план.
2. Закрыть eligibility, non-mutating identity и canonical Match из #199/#212.
3. Утвердить правила #215 и baseline/targets #216.
4. Реализовать versioned manifest, pure generator и Board Lab #213 на fixtures.
5. Подключить frozen stats provider #211 и persistence/events/claims #212.
6. Добавить peer-confirmed state machine #214 с pull-only fallback.
7. Провести ограниченную beta без массовых DM.
8. Только после отдельной проверки включать player delivery и материальные призы.

## Остальной продуктовый backlog

Этот roadmap подробно ведёт текущую стратегическую инициативу. Остальные независимые
задачи остаются в [GitHub Issues](https://github.com/mmbabaev/MetaTheGathering/issues).
Когда новая инициатива становится активным фокусом, для неё нужно добавить сюда
верхнеуровневый status, зависимости, решения и порядок реализации.
