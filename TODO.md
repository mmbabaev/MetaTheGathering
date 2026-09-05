# MetaGatherer — живой план проекта

Последнее обновление: **5 сентября 2026**.

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
- Hardening lifetime-движка из #199: explicit eligibility, read-only identity,
  immutable progress events/replay и независимый owner/player outbox. Player DM
  по-прежнему выключен feature flag по умолчанию и требует персональный opt-in.
- Карта achievement-модуля для разработчиков и агентов — source commit `90ecbf6`,
  PR [#217](https://github.com/mmbabaev/MetaTheGathering/pull/217), merge
  `49768b8`. При подготовке документации прошли 38 focused achievement tests.
- Read-only локальный snapshot сезонной статистики: top decks, H2H, два равных окна
  winrate и quality report — PR [#210](https://github.com/mmbabaev/MetaTheGathering/pull/210).
- Versioned manifest/candidate contracts, fixture-pool для четырёх personas и pure
  deterministic generator 4×4 с diagnostics — PR
  [#239](https://github.com/mmbabaev/MetaTheGathering/pull/239).
- Параметризованная сезонная механика `play_deck` из #200: frozen snapshot создаёт
  candidates «Сыграй турнир на колоде X» с конкретной `general_name`, ручным
  флейворным названием и pure completion evaluator — PR
  [#241](https://github.com/mmbabaev/MetaTheGathering/pull/241).
- Owner/admin команда `/bingo_preview [профиль] [seed]`: read-only генерация fixture-поля,
  PNG 4×4 и текст всех 16 условий. Команда доступна под feature flag
  `achievementBoardLab`, отвечает только инициатору и ничего не записывает в production
  boards — PR [#242](https://github.com/mmbabaev/MetaTheGathering/pull/242).
- Планировщик больше не закрывает незавершённый турнир при создании следующего события:
  вместо потери финального реимпорта создание блокировалось до ручного закрытия — PR
  [#252](https://github.com/mmbabaev/MetaTheGathering/pull/252).
- Колоды из ячейки из [#260](https://github.com/mmbabaev/MetaTheGathering/issues/260): основной
  Telegram-flow `/cellar`, четыре ближайших турнира «Единорога» по понедельникам и четвергам,
  физические копии и деклисты из еженедельно синхронизируемой Google-таблицы, эксклюзивные брони,
  owner-only мгновенные уведомления и одна предтурнирная сводка координаторам. Функция остаётся
  под выключенным по умолчанию `cellarDecks` — PR
  [#261](https://github.com/mmbabaev/MetaTheGathering/pull/261).
- Production-владельцы ячейки Иван и Сергей снова получают мгновенные личные уведомления о каждой
  успешной броне и отмене вместе с владельцем бота. У всех трёх в настройках есть включённый по
  умолчанию персональный тумблер этих мгновенных DM; часовая сводка от него не зависит. Debug
  остаётся owner-only, клубные чаты и другие игроки ничего не получают — PR
  [#265](https://github.com/mmbabaev/MetaTheGathering/pull/265).

- Мета-полиция из [#254](https://github.com/mmbabaev/MetaTheGathering/issues/254): под
  `recordOpponents` любой пользователь может помочь заполнить оставшиеся пустые колоды;
  свой пропуск имеет приоритет, заполненные записи защищены от изменения, автор записи
  сохраняется в `deck_added_by_tg_id` и event log — PR
  [#255](https://github.com/mmbabaev/MetaTheGathering/pull/255).
- Доработка мета-полиции из
  [#258](https://github.com/mmbabaev/MetaTheGathering/issues/258): персональная подсказка
  выделяет незаполненных оппонентов и их раунды; групповое сообщение после каждой записи
  динамически зачёркивает заполненных и убирает кнопку, когда пропусков не осталось — PR
  [#259](https://github.com/mmbabaev/MetaTheGathering/pull/259).
- Owner-only debug-превью мета-полиции воспроизводит живое обновление сообщения на debug-боте,
  не добавляя вторую схему хранения. Даже при нажатии из группы превью и все его обновления
  адресуются только в личку владельца — PR
  [#274](https://github.com/mmbabaev/MetaTheGathering/pull/274).
- Ручная кнопка AetherHub использует дату игрового дня, как плановый импорт, и не предлагает
  старое событие при несовпадении. После второй плановой попытки без турнира владелец бота
  один раз получает в личку дату и Content Feed клуба. Если AetherHub показывает единственную
  строку дня как `DD.MM · Constructed Tourney` без формата, она безопасно принимается только при
  точном совпадении даты и чистом имени-дате — PR
  [#275](https://github.com/mmbabaev/MetaTheGathering/pull/275),
  [#289](https://github.com/mmbabaev/MetaTheGathering/pull/289).
- Онлайн-клуб Endstep-ru с AetherHub Content Feed и временным тестовым Telegram-чатом:
  без расписания, с ручным созданием турнира через club-aware `/create_tournament`.
  Признак online хранится в турнире; для существующих и новых турниров без пометки дефолт — offline — PR
  [#280](https://github.com/mmbabaev/MetaTheGathering/pull/280).
- `/create_tournament` без аргументов открывает пошаговый UI: клуб → момент создания и объявления →
  дата турнира → время → подтверждение. Будущие создания хранятся в БД, переживают рестарты и
  повторяют неудачную отправку объявления без дублирования турнира. В `/clubs` для каждого клуба
  выбирается адрес новых ручных турниров: тестовый чат, без отправки или известный настоящий чат — PR
  [#282](https://github.com/mmbabaev/MetaTheGathering/pull/282).
- Для онлайн-турниров собираются результаты текущего раунда: игрок вводит свои победы и победы
  соперника двумя шагами, второй игрок подтверждает результат либо сразу предлагает правильный.
  Публичная строка матча показывает Telegram-ники, счёт и явный статус; при отсутствии Telegram-ника
  используется имя игрока. Администратор может исправить результат и получить сводку для AetherHub.
  В debug-боте доступны 15 тестовых игроков и Swiss-подобные раунды — PR
  [#284](https://github.com/mmbabaev/MetaTheGathering/pull/284),
  [#287](https://github.com/mmbabaev/MetaTheGathering/pull/287).
- Telegram- и Endstep-ники поддерживаются для сопоставления импортов и публикации парингов, но
  Endstep-ник остаётся необязательным полем настроек и при регистрации не запрашивается — PR
  [#281](https://github.com/mmbabaev/MetaTheGathering/pull/281),
  [#287](https://github.com/mmbabaev/MetaTheGathering/pull/287).
- В настройках Endstep-ru настоящий чат `@endstep_ru` доступен отдельным вариантом; текущий маршрут
  ручных объявлений автоматически не переключается — PR
  [#283](https://github.com/mmbabaev/MetaTheGathering/pull/283).
- Лимит двух активных турниров считается по клубу, а не по техническому адресу объявления:
  `chat_id=0` («не отправлять») и общий debug-чат больше не связывают разные клубы в один лимит — PR
  [#286](https://github.com/mmbabaev/MetaTheGathering/pull/286).

Игрокам ачивки автоматически не рассылаются: текущий режим — owner-only shadow.

### В review, но ещё не в `main`

- Отдельный debug-only beta-режим внутреннего Swiss-движка для онлайн-турниров: администратор
  создаёт первый и следующие раунды после сбора результатов, а бот считает официальные
  match points и OMW/GW/OGW, выдаёт bye снизу без повтора, избегает rematch и балансирует
  pair-up/pair-down. Для 9–32 игроков фиксируется 5 Constructed-раундов по MTR Appendix E.
  Режим opt-in на уровне турнира; AetherHub остаётся дефолтом и не может перезаписать
  внутренние паринги. Правила и ограничения beta описаны в
  [`docs/internal_swiss.md`](docs/internal_swiss.md).

- Защита первой регистрации из [#273](https://github.com/mmbabaev/MetaTheGathering/issues/273):
  ФИО требует минимум два слова с буквами, пробелы и декоративные эмоджи по краям
  отбрасываются; тот же guard закрывает Telegram и web/API-бронирование Cellar.
  После первого непустого импорта AetherHub ещё не найденные там участники динамически
  отмечаются `❓`, а при более позднем появлении отметка исчезает.

- `Spy`/`Spy Combo`, `Spy Walls` и `Walls combo` больше не склеиваются в один сектор
  картинки метагейма; старый `general_name` безопасно исправляется миграцией.
- Ручное закрытие турнира разрешено только администраторам: пустой турнир
  закрывается сразу, а при наличии записанных игроков бот требует подтверждение.
  В турнире сохраняется Telegram ID пользователя, выполнившего закрытие; автоматическое
  закрытие остаётся без автора — PR
  [#276](https://github.com/mmbabaev/MetaTheGathering/pull/276).
- Первая часть этапа 0 Telegram E2E-контура из
  [#270](https://github.com/mmbabaev/MetaTheGathering/issues/270): debug/prod deploy
  сериализуется в GitHub Actions и на сервере, временные архивы и env получают уникальные
  имена и удаляются даже после ошибки, а загрузка останавливается заранее при нехватке места.
  После эксперимента с schema-per-PR debug возвращён к одной постоянной schema: данные больше не «исчезают»
  при деплое другого PR, а конфликты unmerged-миграций исправляются в ветках — PR
  [#285](https://github.com/mmbabaev/MetaTheGathering/pull/285). In-process Telegram
  transport tests и real-bot smoke остаются следующими этапами — PR
  [#271](https://github.com/mmbabaev/MetaTheGathering/pull/271).
- Pure fairness foundation перечисляет все 10 линий Bingo 4×4 и считает вероятностные
  веса/imbalance с отдельными diagnostics для строк, столбцов и диагоналей, не меняя
  horizontal-only `bingo-v1` — PR
  [#250](https://github.com/mmbabaev/MetaTheGathering/pull/250). Персональный estimator и
  weighted solver с hard gate 10% остаются следующими отдельными этапами.
- Fixture-каталог `play_deck` обновляется по production snapshot за год на 19 августа:
  все десять актуальных архетипов получают отдельные preview-цели с ручными названиями.
  Устаревшие Kuldotha Red и Broodscale Combo удаляются из preview-pool; production season
  по-прежнему требует отдельного frozen snapshot на дату старта.
- До двух незакрытых турниров на чат: поздно завершающийся Goldfish не блокирует регистрацию
  следующего события; третий активный турнир по-прежнему запрещён, а неявные операции выбирают
  самый новый.
### Lifetime-движок укреплён

Issue [#199](https://github.com/mmbabaev/MetaTheGathering/issues/199) выполнена:
**7 из 7** архитектурных этапов. Каждое rule объявляет независимые eligibility-гейты;
no-show, ongoing и incomplete history не двигают counters; preview/backfill не
сливают пользователей. Progress имеет immutable before/after events с evidence,
source matches, ruleset/stats version и идемпотентным replay. Owner/player delivery
имеют независимые статусы, versioned payload и targeted recipient.

Автоматические player DM безопасно остаются выключенными: для отправки одновременно
нужны global feature flag, `User.notify_achievements` и `notify_allowed_ids`.
Pull-only UI от delivery не зависит.

### Принятые решения для `bingo-v2`

- Победными считаются все 10 линий поля 4×4: четыре горизонтали, четыре вертикали и две
  диагонали; квадраты 2×2 и углы отдельно не считаются.
- `play_deck` становится накопительной целью «сыграй три турнира на колоде X»; старая
  история используется для baseline, но прогресс начинается только после активации поля.
- Статические `easy/medium/hard/rare` дополняются персональной completion probability и
  весом `−log₂(p)`. Все 10 линий балансируются по dependency-aware joint probability с
  целевым relative imbalance не выше 10%.
- Текущий `bingo-v1` не меняется задним числом. Новая геометрия, counters, contracts и
  diagnostics требуют отдельной algorithm version. Подробный ADR:
  [`docs/achievement_bingo_fairness.md`](docs/achievement_bingo_fairness.md).

### Ещё не реализовано

- `Season`, frozen ruleset/stats snapshot и lifecycle сезона.
- Персональные `Board`, 16 `Cell` и immutable completion/progress events.
- Полный owner Board Lab: реальные игроки, pool/quotas, batch fairness, JSON export и drafts.
- Atomic row/full-board prize claims, tie review и owner approval.
- Player board UI, архив сезона и opt-in sharing.
- Peer-confirmed claims и подтверждение события реальным оппонентом.
- Внешний stats API с абсолютными окнами и стабильными player/deck IDs.

## Карта активных issues

Статусы перечислены на дату обновления. #199 закрыта после завершения hardening;
остальные задачи таблицы остаются открыты.

| Issue | Назначение |
|---|---|
| [#167](https://github.com/mmbabaev/MetaTheGathering/issues/167) | Общий эпик и индекс системы ачивок |
| [#199](https://github.com/mmbabaev/MetaTheGathering/issues/199) | Lifetime hardening — 7/7, issue закрыта |
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

1. Утвердить правила #215 и baseline/targets #216.
2. Подключить generator к owner Board Lab #213 и заменить fixture deck targets реальным
   frozen top-deck catalog первого сезона.
3. Подключить frozen stats provider #211 и persistence/events/claims #212.
4. Добавить peer-confirmed state machine #214 через targeted delivery с pull-only fallback.
5. Провести ограниченную beta без массовых DM.
6. Только после отдельной проверки включать player delivery и материальные призы.

## Остальной продуктовый backlog

Этот roadmap подробно ведёт текущую стратегическую инициативу. Остальные независимые
задачи остаются в [GitHub Issues](https://github.com/mmbabaev/MetaTheGathering/issues).
Когда новая инициатива становится активным фокусом, для неё нужно добавить сюда
верхнеуровневый status, зависимости, решения и порядок реализации.
