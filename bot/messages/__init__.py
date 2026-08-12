# Шаблоны сообщений

# Форматирование ФИО живёт в services/names.py, чтобы одинаково работало и в картинках
# (services-слой). Здесь — реэкспорт для существующих импортов из bot.messages.
from services.names import family_name_sort_key, format_participant_name

NO_ACTIVE_TOURNAMENTS = "Нет активных турниров."
CHOOSE_ARCHETYPE = "Выберите архетип колоды:"
CUSTOM_ARCHETYPE_PROMPT = "Напишите название архетипа:"
REGISTERED_AS = "Вы записаны как {archetype_name}."
REGISTERED = "Вы записаны."
REGISTERED_DECK_LATER = "Вы записаны. Не забудьте указать колоду до начала турнира."
DEFER_DECK_EXPIRED = "Записаться без колоды можно только в первые 7 часов после создания турнира."
ALREADY_REGISTERED = "Вы уже записаны на этот турнир."
REGISTRATION_CLOSED = "Регистрация на этот турнир закрыта."
TOURNAMENT_NOT_FOUND = "Турнир не найден."
LEAVE_CONFIRM_PROMPT = "Вы уверены, что хотите выйти из турнира?"
LEFT_TOURNAMENT = "Вы вышли из турнира."
NOT_REGISTERED_IN_TOURNAMENT = "Вы не записаны на этот турнир."


# Name prompts
ASK_NAME = "Как вас зовут? Введите фамилию и имя через пробел (например: Иванов Иван):"
NAME_SAVED = "Имя сохранено: {full_name}"
NAME_REQUIRED_FOR_REGISTRATION = (
    "Для записи на турнир нужно указать ваше имя.\n\nВведите фамилию и имя через пробел (например: Иванов Иван):"
)

# Settings
SETTINGS_MENU = "⚙️ Настройки"
SETTINGS_CHANGE_NAME_PROMPT = "Введите фамилию и имя через пробел (например: Иванов Иван):"

# Admin messages
NOT_ADMIN = "У вас нет прав администратора."
NO_ACTIVE_TOURNAMENT = "Нет активного турнира в этом чате."
PLAYER_ADDED = "✅ {user} добавлен как {archetype_name}."
TELEGRAM_USER_LOOKUP_FAILED = "Не удалось найти @{username} в Telegram. Проверьте @username."
TOURNAMENT_CLOSED_MSG = "Турнир закрыт."
TOURNAMENT_ALREADY_EXISTS_MSG = "В этом чате уже есть активный турнир."
MULTIPLE_TOURNAMENTS_MSG = "Активных турниров несколько. Используйте /tournament_status чтобы увидеть их ID."
ADD_PLAYERS_USAGE = "Формат:\n/add_players\n@username1 Название колоды\n@username2 Другая колода"
BULK_ADD_PROMPT = (
    "Введите список игроков — по одному на строке (Фамилия Имя):\n\nПример:\nИванов Иван\nПетрова Мария\nАлексей"
)
BULK_ADD_EMPTY = "Список игроков пустой."
PARTICIPANT_NOT_FOUND = "Участник не найден."
SCOREKEEPER_GRANTED = "🧙 {name} назначен метаписцем."
SCOREKEEPER_REVOKED = "🧙 {name} снят с роли метаписца."
POLL_ORGANIZER_GRANTED = "📊 {name} назначен организатором голосований."
POLL_ORGANIZER_REVOKED = "📊 {name} снят с роли организатора голосований."
ADMIN_ARCH_SAVED = "✅ Колода обновлена: {archetype_name}"
DECKS_REVEALED = "👁 Колоды участников теперь видны всем."
META_IMPORT_PROMPT = (
    "Отправьте таблицу в формате:\n\n"
    "## Игроки\n"
    "Фамилия Имя | Колода\n\n"
    "## Раунд 1\n"
    "Фамилия Имя 2-1 Фамилия Имя\n\n"
    "Используйте /recognize-meta в Claude Code для распознавания фото."
)


# Achievements (пока теневой режим — видят только владелец и админы)
ACHIEVEMENTS_HEADER = "🏅 {title} — {unlocked} из {total}"
ACHIEVEMENTS_UNLOCKED_TITLE = "Открыто"
ACHIEVEMENTS_PROGRESS_TITLE = "В процессе"
ACHIEVEMENTS_LOCKED_TITLE = "Закрыто"
ACHIEVEMENTS_EMPTY = "Пока ачивок нет."
ACHIEVEMENTS_UNAVAILABLE = "Команда пока недоступна."
ACHIEVEMENTS_PLAYER_NOT_FOUND = "Игрок «{query}» не найден."

HELP_TEXT = """\
/tournaments — посмотреть активные турниры и записаться
  Выберите турнир → укажите колоду → готово.
  Можно изменить колоду в любой момент, пока идёт регистрация.

/settings — сохранить имя и фамилию для автоматической записи\
"""

HELP_TEXT_ADMIN = """\
Команды администратора:

/tournament_status — список участников всех активных турниров
/archive — архив закрытых турниров

/create_tournament — создать новый турнир вручную
/delete_tournament — удалить текущий турнир

/add_players — массовая запись (каждая строка: Имя Фамилия)

/poll — меню организатора голосований: регуляры клуба и «кому ещё написать»

/achievements — полка ачивок; /achievements Иванов — посмотреть чужую\
"""


def _participant_icon(p) -> str:
    """✅ колода указана / ⬜ колоды нет."""
    return "✅" if p.archetype else "⬜"


# Типичные окончания русских фамилий


def sort_participants(participants: list) -> list:
    """Сортирует участников: сначала без колоды, затем с колодой; внутри — по фамилии."""

    def _key(p):
        filled = 0 if p.archetype is None else 1
        name = family_name_sort_key(
            p.user.first_name if p.user else None,
            p.user.last_name if p.user else None,
        )
        return (filled, name)

    return sorted(participants, key=_key)


def format_tournament_card(
    title: str,
    status: str,
    slug: str | None = None,
    total: int | None = None,
    with_deck: int | None = None,
) -> str:
    """Компактная карточка турнира с опциональным счётчиком участников."""
    header = f"🏆 {title} · {status}"
    if total is not None:
        if with_deck is not None:
            without = total - with_deck
            header += f" · {total} чел. ({with_deck} ✅ / {without} ⬜)"
        else:
            header += f" · {total} чел."
    return header


def _status_header(title: str, status: str, participants: list) -> str:
    total = len(participants)
    with_deck = sum(1 for p in participants if p.archetype)
    header = f"🏆 {title} · {status} · {total} чел."
    if total:
        header += f"\n✅ {with_deck} с колодой  ⬜ {total - with_deck} без"
    return header


def format_participant_line(p, decks_hidden: bool = False) -> str:
    """Одна строка участника: «<иконка> Фамилия Имя (@ник) 🧙 — Колода». Общий для обоих режимов."""
    icon = _participant_icon(p)
    if p.user:
        full_name = format_participant_name(p.user.first_name, p.user.last_name) or f"id{p.user.tg_id}"
        username_hint = f" (@{p.user.username})" if p.user.username else ""
        sk_badge = " 🧙" if getattr(p.user, "is_scorekeeper", False) else ""
        display = f"{full_name}{username_hint}{sk_badge}"
    else:
        display = "?"
    if p.archetype:
        archetype = "▓▓▓" if decks_hidden else p.archetype.name
    else:
        archetype = "не указана"
    return f"{icon} {display} — {archetype}"


def format_tournament_status(title: str, status: str, participants: list, decks_hidden: bool = False) -> str:
    """Структурированный список участников турнира (плоский)."""
    lines = [_status_header(title, status, participants), ""]
    lines.extend(format_participant_line(p, decks_hidden) for p in participants)
    return "\n".join(lines)


def format_decks_revealed(title: str, total: int, with_deck: int, meta_rows: list, top_n: int = 8) -> str:
    """Анонс в чат при авто-раскрытии колод: турнир, счётчики, топ колод.

    ``meta_rows`` — список с атрибутами ``archetype_name``/``count`` (StatsService.MetaRow),
    отсортированный по убыванию count.
    """
    lines = [f"👁 Колоды раскрыты — {title}", f"Участников: {total} ({with_deck} с колодой)"]
    if meta_rows:
        lines.append("")
        lines.append("Топ колод:")
        lines.extend(f"{i}. {row.archetype_name} — {row.count}" for i, row in enumerate(meta_rows[:top_n], 1))
    return "\n".join(lines)


def format_meta_gather_completed(
    title: str, total: int, with_deck: int, undefeated: list, scorekeepers: list = ()
) -> str:
    """Анонс «сбор метагейма завершён»: турнир, счётчики, игроки без поражений и их колоды.

    ``undefeated`` — список с атрибутами ``first_name``/``last_name``/``player_name``/
    ``archetype_name``/``wins`` (services.aetherhub_import_service.UndefeatedPlayer),
    отсортированный по финальному месту.
    ``scorekeepers`` — метаписцы (services.tournament.DeckRecorder): ``username``/``first_name``/
    ``last_name``/``count``, отсортированы по убыванию количества записанных колод.
    """
    lines = [f"🎉 Сбор метагейма завершён — {title}", f"Участников: {total} ({with_deck} с колодой)"]
    if undefeated:
        lines.append("")
        lines.append(f"Без поражений ({undefeated[0].wins}-0):")
        for u in undefeated:
            name = format_participant_name(u.first_name, u.last_name) or u.player_name
            deck = u.archetype_name or "колода неизвестна"
            lines.append(f"• {name} — {deck}")
    if scorekeepers:
        lines.append("")
        lines.append("🙏 Спасибо за записанные колоды:")
        for s in scorekeepers:
            name = format_participant_name(s.first_name, s.last_name) or "?"
            handle = f"@{s.username} " if s.username else ""
            lines.append(f"• {handle}{name} — {s.count}")
    return "\n".join(lines)


def _game_noun(n: int) -> str:
    """Склонение «партия» (bo3-игра). DataLens отдаёт число партий, не матчей."""
    if 11 <= n % 100 <= 14:
        return "партий"
    rem = n % 10
    if rem == 1:
        return "партия"
    if 2 <= rem <= 4:
        return "партии"
    return "партий"


def format_opponent_notification(
    round_number: int,
    table_number: int | None,
    opponent_name: str | None,
    opponent_username: str | None,
    opponent_decks: list[str] | None = None,
    is_bye: bool = False,
    *,
    datalens_decks: list | None = None,
    head_to_head=None,
) -> str:
    """Личное сообщение игроку о его паре в новом раунде.

    ``datalens_decks`` / ``head_to_head`` — обогащение из DataLens (объекты с
    атрибутами ``name``/``matches``/``winrate``; ``matches`` — это число сыгранных
    партий bo3, а не матчей). Если переданы — показываем колоды оппонента с ЕГО
    винрейтом на них и число личных партий с твоим винрейтом; иначе откатываемся
    на список колод из БД бота (``opponent_decks``).
    """
    if is_bye:
        return f"🔔 Раунд {round_number}\n\nВ этом раунде у тебя бай — отдыхай! 🎉"

    lines = [f"🔔 Раунд {round_number}"]
    if table_number is not None:
        lines.append(f"Стол №{table_number}")

    opponent = opponent_name or "?"
    if opponent_username:
        opponent += f" (@{opponent_username})"
    lines.append("Оппонент:")
    lines.append(opponent)

    if datalens_decks:
        lines.append("")
        lines.append("Колоды оппонента и общий винрейт (3 мес):")
        lines.extend(f"• {d.name} — {round(d.winrate)}% ({d.matches} {_game_noun(d.matches)})" for d in datalens_decks)
    elif opponent_decks:
        lines.append("")
        lines.append("Последние колоды оппонента:")
        lines.extend(f"• {name}" for name in opponent_decks)
    else:
        lines.append("")
        lines.append("Колоды оппонента в прошлых турнирах не найдены.")

    if head_to_head is not None:
        lines.append("")
        lines.append(f"Партий против оппонента: {head_to_head.matches}, твой винрейт {round(head_to_head.winrate)}%")

    return "\n".join(lines)


# ── Расписание клубов (issue #124/#125) ──────────────────────────────────────


def schedule_row_label(row) -> str:
    """Подпись строки расписания для кнопки: «🐠 Goldfish · пятница ✅»."""
    from core.clubs import club_identities  # noqa: PLC0415 — иначе цикл импортов
    from services.schedule import WEEKDAY_RU  # noqa: PLC0415

    prefix = next((c.title_prefix for c in club_identities() if c.name == row.club_name), "")
    day = WEEKDAY_RU.get(row.weekday, row.weekday)
    mark = "✅" if row.enabled else "⏸"
    return f"{prefix}{row.club_name} · {day} {mark}"


def format_schedule_rows(rows, tz: str) -> str:
    """Текст /schedule по строкам из БД — включая выключенные (их в планировщике нет)."""
    from services.schedule import WEEKDAY_RU, parse_import_times  # noqa: PLC0415

    if not rows:
        return "📅 Расписание пусто."

    lines = [f"📅 Расписание ({tz}):"]
    current_club = None
    for row in rows:
        if row.club_name != current_club:
            current_club = row.club_name
            lines.append(f"\n{row.club_name}:")
        day = WEEKDAY_RU.get(row.weekday, row.weekday)
        status = "" if row.enabled else "  ⏸ выключено"
        lines.append(f"  {day}: создание {row.create_time}, игра {row.game_time}{status}")
        if row.reminder_time:
            lines.append(f"    напоминание: {row.reminder_time}")
        times = parse_import_times(row.import_times)
        if times:
            lines.append(f"    импорт: {', '.join(times)}")
    return "\n".join(lines)
