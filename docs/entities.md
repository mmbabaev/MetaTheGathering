# Entities

→ [ER Diagram](er-diagram.md)

Сущности двух типов:
- **DB-таблицы** — хранятся в PostgreSQL
- **Config-объекты** — определены в коде (`core/config.py`), не в БД

---

## User

Telegram-пользователь. Создаётся автоматически при первом взаимодействии с ботом.

| Поле | Тип | Описание |
|------|-----|----------|
| `tg_id` | bigint | Telegram user ID (уникальный) |
| `username` | string | @username (может быть null) |
| `first_name` | string | Имя |
| `is_admin` | bool | Может управлять турниром |
| `is_superadmin` | bool | Полный доступ |

---

## Tournament

Один турнирный день. Привязан к Telegram-чату клуба.

| Поле | Тип | Описание |
|------|-----|----------|
| `title` | string | Название, напр. `Goldfish Pauper 2026-04-24` |
| `chat_id` | bigint | ID группового чата в Telegram |
| `slug` | string | URL-идентификатор, напр. `2026-04-24-goldfish-pauper` |
| `status` | enum | `REGISTRATION → ONGOING → VOTING → CLOSED` |
| `club` | string | `Goldfish` / `Edinorog` / null |
| `aetherhub_url` | string | Ссылка на турнир в AetherHub |
| `decks_hidden` | bool | Скрывать архетипы до конца турнира |

**Статусы:**
- `REGISTRATION` — открыта запись игроков
- `ONGOING` — турнир идёт
- `VOTING` — голосование за архетипы
- `CLOSED` — завершён

---

## Archetype

Архетип колоды (Burn, Affinity, и т.д.). Глобальный справочник, не привязан к турниру.

| Поле | Тип | Описание |
|------|-----|----------|
| `name` | string | Полное название (уникальное) |
| `short_name` | string | Аббревиатура, напр. `RDW` |
| `color_emoji` | string | Эмодзи цветов, напр. `🔴` |
| `meta_rank` | int | Позиция в мета-топе (1 = первый; null = вне топа) |
| `is_custom` | bool | Введён игроком вручную; не показывается в глобальном топе |

---

## ArchetypeAlias

Синонимы для поиска архетипа по названию (фаззи-матчинг).

Пример: `Burn` → алиасы `rdw`, `красный`, `огонь`.

| Поле | Тип | Описание |
|------|-----|----------|
| `archetype_id` | FK | Ссылка на Archetype |
| `alias` | string | Синоним (уникальный в рамках архетипа) |

---

## Participant

Участие конкретного пользователя в конкретном турнире.
Пара `(tournament_id, user_id)` уникальна.

| Поле | Тип | Описание |
|------|-----|----------|
| `tournament_id` | FK | Турнир |
| `user_id` | FK | Игрок |
| `archetype_id` | FK | Выбранный архетип (null = не указан) |
| `confirmed` | bool | Архетип подтверждён голосованием или админом |
| `upvotes_count` | int | Кол-во голосов «за» |
| `downvotes_count` | int | Кол-во голосов «против» |
| `added_by_admin` | bool | Добавлен вручную (не через /register) |
| `deck_added_by_tg_id` | bigint | Кто добавил архетип (игрок / админ / оппонент) |

**Логика подтверждения:**
- `upvotes − downvotes ≥ 3` → `confirmed = true`
- `downvotes − upvotes ≥ 3` → `confirmed = false`

---

## Vote

Голос одного пользователя за архетип участника. Один voter → один голос на participant в рамках турнира.

| Поле | Тип | Описание |
|------|-----|----------|
| `tournament_id` | FK | Турнир |
| `participant_id` | FK | Участник, за которого голосуют |
| `voter_id` | FK | Голосующий |
| `vote_type` | enum | `UP` или `DOWN` |

---

## UserDeckHistory

История колод игрока из внешних источников (импорт из AetherHub и т.п.).
Используется как подсказка при регистрации. Не привязана к турниру.

| Поле | Тип | Описание |
|------|-----|----------|
| `user_id` | FK | Игрок |
| `archetype_id` | FK | Архетип |
| `source` | string | Источник, напр. `aetherhub_import` |

Пара `(user_id, archetype_id)` уникальна.

---

## TournamentPoll

Telegram-опрос «Пойду / Не пойду», привязанный к турниру (1:1).

| Поле | Тип | Описание |
|------|-----|----------|
| `tournament_id` | FK | Турнир (уникальный) |
| `tg_poll_id` | string | ID опроса в Telegram |
| `message_id` | bigint | ID сообщения с опросом |
| `chat_id` | bigint | Чат, в котором опубликован опрос |

---

## PollVote

Голос одного пользователя в опросе турнира.

| Поле | Тип | Описание |
|------|-----|----------|
| `poll_id` | FK | Опрос |
| `tg_user_id` | bigint | Telegram user ID голосующего |
| `choice` | int | `0` = пойду, `1` = не пойду |

---

## RoundPairing

Паринг одного игрока в раунде турнира. Импортируется из AetherHub.

| Поле | Тип | Описание |
|------|-----|----------|
| `tournament_id` | FK | Турнир |
| `round_number` | int | Номер раунда |
| `player_name` | string | Имя игрока (как на AetherHub) |
| `opponent_name` | string | Имя оппонента (null = bye) |

Тройка `(tournament_id, round_number, player_name)` уникальна.

---

## Club *(config)*

Конфигурация клуба. Не хранится в БД — определена в коде (`core/config.py`).
`Club.name` соответствует полю `Tournament.club`.

| Поле | Тип | Описание |
|------|-----|----------|
| `name` | string | Уникальное имя клуба (`Goldfish`, `Edinorog`) |
| `chat_id` | int | Telegram chat ID группы клуба |
| `aetherhub_url` | string | URL страницы клуба на AetherHub |
| `title_prefix` | string | Префикс в названии турнира (напр. `🦄 `) |
| `schedules` | list | Список расписаний (ClubSchedule) |

---

## ClubSchedule *(config)*

Расписание одного игрового дня клуба. Клуб может иметь несколько расписаний (напр. Goldfish — пятница и суббота).

| Поле | Тип | Описание |
|------|-----|----------|
| `weekday` | string | День недели (`friday`, `saturday`, …) |
| `game_time` | string | Время начала турнира (`19:30`) |
| `create_time` | string | Время создания турнира-записи (переопределяет дефолт) |
| `aetherhub_fetch_times` | list | Времена для автоимпорта из AetherHub (`["20:15", "21:00"]`) |
