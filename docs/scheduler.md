# Автоматические действия (scheduler)

Все автоматические действия по времени и событиям живут в `bot/scheduler.py`
(`setup_scheduler()`), которая регистрирует джобы в `app.job_queue` PTB. Времена
указаны в таймзоне `settings.TOURNAMENT_TIMEZONE` (по умолчанию из конфига клуба,
обычно Europe/Moscow).

Два типа автоматизации:
- **по времени** — `run_daily` / `run_repeating` (джобы ниже);
- **по событию** — действия, которые срабатывают внутри импорта при изменении
  данных (новые раунды → уведомления; см. раздел «Событийные действия»).

## Расписание клубов (`get_clubs()`)

Каждый клуб задаёт дни недели и времена. Турнир создаётся в `create_time`, игра в
`game_time`, импорт с AetherHub — в каждое из `aetherhub_fetch_times`.

| Клуб | День | create_time | game_time | aetherhub_fetch_times |
|------|------|-------------|-----------|------------------------|
| 🐠 Goldfish | четверг | 03:10 | 19:45 | 20:00–00:30 каждые 30 мин |
| 🐠 Goldfish | пятница | 12:00 | 19:45 | 20:00–00:30 каждые 30 мин |
| 🦄 Edinorog | понедельник | 12:00 | 19:30 | 20:00–00:30 каждые 30 мин |
| [DEBUG] 🐠 | четверг | 12:30 | 12:30 | 12:31 (только при `settings.DEBUG`) |

`chat_id` клуба берётся из конфига (`goldfish_chat_id` / `edinorog_chat_id`).

## Джобы по времени

### 1. Создание турнира — `CreateTournamentJob`
- **Когда:** `run_daily` в `create_time` в нужный день недели (по одной джобе на расписание).
- **Что делает:** закрывает предыдущий активный турнир клуба → создаёт новый в статусе `REGISTRATION` → если задан `settings.OWNER_CHAT_ID`, шлёт владельцу в личку анонс «Турнир создан. Регистрация открыта».
- Название: `<emoji> <Клуб> Pauper <дата>`.

### 2. Плановый импорт с AetherHub — `AetherhubImportJob`
- **Когда:** `run_daily` в каждое `aetherhub_fetch_time` в день расписания (по джобе на каждое время).
- **Что делает:** находит сегодняшний Pauper-турнир клуба на странице AetherHub клуба (`find_todays_pauper_tournament`) → импортирует (`import_tournament`: участники, паринги, счёт) → сохраняет `aetherhub_url` турнира. При новых раундах — уведомления об оппоненте (см. ниже).

### 3. Поминутный импорт по флагу турнира — `AetherhubTimedImportJob`
- **Когда:** `run_repeating` каждые 60 секунд.
- **Что делает:** импортирует турниры, у которых `aetherhub_import_time` == текущее `ЧЧ:ММ` и статус ≠ `CLOSED`. Время выставляет админ кнопкой в карточке турнира. При новых раундах — уведомления об оппоненте.

### 4. Финальный реимпорт счёта — `AetherhubFinalReimportJob` (`FINAL_REIMPORT_TIME = 06:00`)
- **Когда:** `run_daily` в 06:00.
- **Что делает:** перезатягивает турниры, созданные за последние `FINAL_REIMPORT_WINDOW_DAYS` (2) дня, чтобы добрать **финальный счёт** матчей. На AetherHub per-match счёт появляется только ПОСЛЕ завершения турнира (страница меняет формат js → edinorog, см. [`aetherhub_formats.md`](aetherhub_formats.md)), поэтому импорт во время игры его не видит. Уведомлений нет — только добор счёта.

### 5. Авто-раскрытие колод — `AutoRevealDecksJob` (`REVEAL_DECKS_TIME = 22:00`)
- **Когда:** `run_daily` в 22:00.
- **Что делает:** снимает `decks_hidden` у незакрытых турниров, созданных сегодня (во время регистрации колоды скрыты, чтобы их не копировали). Затем шлёт **один** анонс владельцу в личку (`settings.OWNER_CHAT_ID`, НЕ в чат турнира — пока так и в debug, и в prod): «👁 Колоды раскрыты», счётчики участников и короткую мету (топ колод из `StatsService.get_tournament_meta`). Анонс best-effort: сбой отправки не роняет джобу; нет `OWNER_CHAT_ID` — пропускается.

## Событийные действия (внутри импорта)

### Уведомления об оппоненте на новом раунде
Срабатывают в `AetherhubImportJob` и `AetherhubTimedImportJob`, когда `import_tournament`
возвращает новые номера раундов (`result.new_round_numbers`). Каждому
само-зарегистрированному игроку, включившему opt-in «Уведомления об оппоненте» в
`/settings` (`notify_opponent_rounds`, по умолчанию ВЫКЛ), отправляется ЛС о его паре:
стол, оппонент, его колоды и винрейт из DataLens (best-effort). Реализация —
`bot/telegram/round_notify.py` + `bot/handlers/round_notify.py`. Рассылка уважает
allow-list `notify_allowed_ids`.

## Где менять

- **Дни/времена/клубы:** `get_clubs()` в `bot/scheduler.py`.
- **Времена общих джоб:** константы `FINAL_REIMPORT_TIME`, `REVEAL_DECKS_TIME`,
  `FINAL_REIMPORT_WINDOW_DAYS` в `bot/scheduler.py`.
- **Регистрация джоб:** `setup_scheduler()` — там `run_daily` / `run_repeating`.
- **Таймзона:** `settings.TOURNAMENT_TIMEZONE`.

> Все джобы логируются (`logger.info`/`exception`) с префиксом имени джобы — искать
> в `journalctl` по `AetherhubFinalReimportJob`, `AutoRevealDecksJob` и т.п.
