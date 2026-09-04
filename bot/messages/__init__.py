# Шаблоны сообщений

from collections import Counter
from html import escape

from core.models import RoundMatchStatus

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
    "Для записи на турнир нужно указать фамилию и имя — минимум два слова с буквами.\n\n"
    "Введите фамилию и имя через пробел (например: Иванов Иван):"
)
INVALID_FULL_NAME = (
    "Нужно указать фамилию и имя — минимум два слова с буквами.\n\n"
    "Введите фамилию и имя через пробел (например: Иванов Иван):"
)
ENDSTEP_USERNAME_REQUIRED = (
    "Для записи на онлайн-турнир нужен ник Endstep.\n\nВведите точный ник, под которым вы играете на Endstep/AetherHub:"
)
ENDSTEP_USERNAME_INVALID = "Ник Endstep должен быть одной непустой строкой длиной до 255 символов."
ENDSTEP_USERNAME_TAKEN = "Этот ник Endstep уже указан у другого пользователя. Проверьте написание."
ENDSTEP_USERNAME_SAVED = "Ник Endstep сохранён: {username}"

# Settings
SETTINGS_MENU = "⚙️ Настройки"
SETTINGS_CHANGE_NAME_PROMPT = "Введите фамилию и имя через пробел (например: Иванов Иван):"
SETTINGS_CHANGE_ENDSTEP_USERNAME_PROMPT = "Введите точный ник, под которым вы играете на Endstep/AetherHub:"

# Admin messages
NOT_ADMIN = "У вас нет прав администратора."
NO_ACTIVE_TOURNAMENT = "Нет активного турнира в этом чате."
PLAYER_ADDED = "✅ {user} добавлен как {archetype_name}."
TELEGRAM_USER_LOOKUP_FAILED = "Не удалось найти @{username} в Telegram. Проверьте @username."
TOURNAMENT_CLOSED_MSG = "Турнир закрыт."
TOURNAMENT_ALREADY_EXISTS_MSG = "В этом чате уже открыты два турнира — сначала закройте один."
MULTIPLE_TOURNAMENTS_MSG = "Активных турниров несколько. Используйте /tournament_status чтобы увидеть их ID."
ADD_PLAYERS_USAGE = "Формат:\n/add_players\n@username1 Название колоды\n@username2 Другая колода"
BULK_ADD_PROMPT = (
    "Введите список игроков — по одному на строке (Фамилия Имя):\n\nПример:\nИванов Иван\nПетрова Мария\nАлексей"
)
BULK_ADD_EMPTY = "Список игроков пустой."
PARTICIPANT_NOT_FOUND = "Участник не найден."
META_POLICE_FILL_UNAVAILABLE = "Заполнение колод по этому напоминанию сейчас недоступно."
META_POLICE_DECK_ALREADY_FILLED = "Этому игроку уже указали колоду. Выберите другого."
META_POLICE_ALL_FILLED = "✅ Все колоды уже заполнены. Спасибо!"
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

# Owner/admin bingo preview
BINGO_PREVIEW_USAGE = (
    "Формат: /bingo_preview [профиль] [seed]\n"
    "Профили: newcomer/новичок, amateur/любитель, regular/регуляр, pro/про.\n"
    "Примеры:\n"
    "/bingo_preview\n"
    "/bingo_preview новичок\n"
    "/bingo_preview regular 42"
)
BINGO_PREVIEW_DISABLED = "Bingo preview отключён feature flag achievementBoardLab."
BINGO_PREVIEW_FAILED = "Не удалось собрать поле с выбранными параметрами."

# Cellar deck reservations
CELLAR_UNAVAILABLE = "Колоды из ячейки пока недоступны."
CELLAR_DATES = (
    "🗄 Колоды из ячейки\n\nВыберите дату турнира в Единороге. Бронь автоматически попадёт в запись на турнир."
)
CELLAR_USER_NOT_FOUND = "Сначала откройте /cellar ещё раз."
CELLAR_CANCELLED = "Бронь отменена."
CELLAR_RESERVED = "Колода забронирована."


def format_cellar_catalog(event_date, decks: list, user_id: int) -> str:
    free = 0
    own = None
    for deck in decks:
        reservation = next(
            (row for row in deck.reservations if row.event_date == event_date and row.cancelled_at is None),
            None,
        )
        if deck.available and reservation is None:
            free += 1
        if reservation is not None and reservation.user_id == user_id:
            own = deck.display_name
    lines = [
        f"🗄 Колоды из ячейки на {event_date.strftime('%d.%m.%Y')}",
        "",
        f"Свободно: {free} из {len(decks)}.",
        "▫️ свободна · 🔒 занята · 🚫 недоступна",
    ]
    if own:
        lines.extend(["", f"Ваша бронь: ✅ {own}"])
    lines.extend(["", "Выберите физическую колоду. Номер № — её строка в таблице."])
    return "\n".join(lines)


def format_cellar_deck(deck, reservation, user_id: int, user_has_other_reservation: bool) -> str:
    lines = [f"🗄 {deck.display_name}", "", f"Архетип: {deck.archetype_name}"]
    if deck.notes:
        lines.append(f"Примечание: {deck.notes}")
    if deck.decklist_updated_on:
        lines.append(f"Деклист актуален на {deck.decklist_updated_on.strftime('%d.%m.%Y')}")
    lines.append("")
    if not deck.available:
        lines.append("Статус: 🚫 недоступна")
    elif reservation is None:
        lines.append("Статус: ▫️ свободна")
        if user_has_other_reservation:
            lines.append("На эту дату у вас уже забронирована другая колода.")
    elif reservation.user_id == user_id:
        lines.append("Статус: ✅ забронирована вами")
    else:
        user = reservation.user
        name = (
            user.display_name
            or " ".join(part for part in (user.first_name, user.last_name) if part)
            or f"id{user.tg_id}"
        )
        lines.append(f"Статус: 🔒 забронировал(а) {name}")
    return "\n".join(lines)


def format_cellar_cancel_prompt(reservation) -> str:
    return f"Отменить бронь?\n\n{reservation.deck.display_name} — {reservation.event_date.strftime('%d.%m.%Y')}"


HELP_TEXT = """\
/tournaments — посмотреть активные турниры и записаться
  Выберите турнир → укажите колоду → готово.
  Можно изменить колоду в любой момент, пока идёт регистрация.

/cellar — выбрать и забронировать колоду из ячейки

/settings — сохранить имя и фамилию для автоматической записи\
"""

HELP_TEXT_ADMIN = """\
Команды администратора:

/tournament_status — список участников всех активных турниров
/archive — архив закрытых турниров

/create_tournament — создать турнир вручную
  Endstep-ru: /create_tournament --club Endstep-ru [название]
/clubs — выбрать чат для объявлений ручных турниров
/delete_tournament — удалить текущий турнир

/add_players — массовая запись (каждая строка: Имя Фамилия)

/poll — меню организатора голосований: регуляры клуба и «кому ещё написать»

/achievements — полка ачивок; /achievements Иванов — посмотреть чужую\

/bingo_preview [профиль] [seed] — пример bingo-поля 4×4\
"""


def _participant_icon(p, *, aetherhub_imported: bool = False) -> str:
    """✅ колода указана / ⬜ колоды нет; ❓ игрок ещё не найден в AetherHub."""
    icon = "✅" if p.archetype else "⬜"
    if aetherhub_imported and getattr(p, "aetherhub_seen_at", None) is None:
        icon += "❓"
    return icon


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


def format_participant_line(p, decks_hidden: bool = False, *, aetherhub_imported: bool = False) -> str:
    """Одна строка участника: «<иконка> Фамилия Имя (@ник) 🧙 — Колода». Общий для обоих режимов."""
    icon = _participant_icon(p, aetherhub_imported=aetherhub_imported)
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
    aetherhub_imported = any(getattr(p, "aetherhub_seen_at", None) is not None for p in participants)
    lines = [_status_header(title, status, participants), ""]
    lines.extend(format_participant_line(p, decks_hidden, aetherhub_imported=aetherhub_imported) for p in participants)
    if aetherhub_imported and any(getattr(p, "aetherhub_seen_at", None) is None for p in participants):
        lines.extend(["", "❓ — пока не найден в AetherHub"])
    return "\n".join(lines)


def _round_match_names(matches: list) -> dict[tuple[int, int], str]:
    """Compact family names, expanded only when two players would look identical."""
    compact: dict[tuple[int, int], str] = {}
    full: dict[tuple[int, int], str] = {}
    for match in matches:
        for position, (source_name, user) in enumerate(
            ((match.player1_name, match.player1_user), (match.player2_name, match.player2_user)), start=1
        ):
            if source_name is None:
                continue
            key = (match.id, position)
            if user is not None:
                compact[key] = user.last_name or user.first_name or source_name
                full[key] = format_participant_name(user.first_name, user.last_name) or source_name
            else:
                compact[key] = source_name
                full[key] = source_name
    counts = Counter(value.casefold() for value in compact.values())
    return {key: (full[key] if counts[value.casefold()] > 1 else value) for key, value in compact.items()}


def format_round_pairings(title: str, status: str, round_number: int, matches: list) -> str:
    """Latest-round public status with live pending and final scores."""
    names = _round_match_names(matches)
    playable = [match for match in matches if match.player2_name is not None]
    completed = sum(
        match.status in {RoundMatchStatus.CONFIRMED, RoundMatchStatus.ADMIN, RoundMatchStatus.IMPORTED}
        for match in playable
    )
    lines = [
        f"🎮 {escape(title)} · {escape(status)}",
        f"<b>Раунд {round_number} · результаты {completed}/{len(playable)}</b>",
        "",
    ]
    for index, match in enumerate(matches, start=1):
        table = match.table_number if match.table_number is not None else index
        left = escape(names[(match.id, 1)])
        if match.player2_name is None:
            lines.append(f"{table}. {left} — BYE ✅")
            continue
        right = escape(names[(match.id, 2)])
        if match.player1_wins is None or match.player2_wins is None:
            lines.append(f"{table}. {left} — {right}")
            continue
        icon = "⏳" if match.status == RoundMatchStatus.PENDING else "✅"
        lines.append(f"{table}. {left} <b>{match.player1_wins}–{match.player2_wins}</b> {right} {icon}")
    lines.extend(["", "✅ подтверждено · ⏳ ожидает соперника"])
    return "\n".join(lines)


def format_aetherhub_round_summary(round_number: int, matches: list) -> str:
    """Copyable scorekeeper summary preserving source/AetherHub player order."""
    lines = [f"Раунд {round_number}", ""]
    for index, match in enumerate(matches, start=1):
        table = match.table_number if match.table_number is not None else index
        if match.player2_name is None:
            lines.append(f"Стол {table}: {match.player1_name} — BYE")
        elif match.player1_wins is None or match.player2_wins is None:
            lines.append(f"Стол {table}: {match.player1_name} — {match.player2_name}")
        else:
            lines.append(
                f"Стол {table}: {match.player1_name} {match.player1_wins}-{match.player2_wins} {match.player2_name}"
            )
    return "\n".join(lines)


def format_missing_decks_reminder(title: str, participants: list, community_fill_enabled: bool = False) -> str:
    """HTML-текст мета-полиции; заполненные после отправки строки зачёркнуты."""
    all_filled = bool(participants) and all(participant.archetype_id is not None for participant in participants)
    lines = [
        "🚨👮 Вас посетила мета-полиция!",
        "На какой колоде были эти игроки?",
    ]
    if community_fill_enabled:
        lines.append(
            "✅ Все колоды заполнены — спасибо!"
            if all_filled
            else "Помочь заполнить пропуски может каждый — нажмите «Записать»."
        )
    lines.extend(["", f"🏆 {escape(title)}", "Список игроков без колоды:"])
    for participant in participants:
        user = participant.user
        name = format_participant_name(user.first_name, user.last_name) or f"id{user.tg_id}"
        username = f" (@{user.username})" if user.username else ""
        line = f"• {escape(name)}{escape(username)}"
        lines.append(f"<s>{line}</s>" if participant.archetype_id is not None else line)
    return "\n".join(lines)


def format_unfilled_opponents_note(opponents: list) -> str:
    """Персональная подсказка: какие оппоненты пользователя всё ещё без колоды."""
    if not opponents:
        return ""
    lines = ["Твои незаполненные оппоненты:"]
    for opponent in opponents:
        participant = opponent.participant
        user = participant.user
        name = format_participant_name(user.first_name, user.last_name) or f"id{user.tg_id}"
        lines.append(f"• {name} — раунд {opponent.round_number}")
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
    from core.clubs import club_identities  # noqa: PLC0415 — иначе цикл импортов
    from services.schedule import WEEKDAY_RU, parse_import_times  # noqa: PLC0415

    if not rows:
        return "📅 Расписание пусто."

    lines = [f"📅 Расписание ({tz}):"]
    club_timezones = {club.name: club.timezone for club in club_identities()}
    current_club = None
    for row in rows:
        if row.club_name != current_club:
            current_club = row.club_name
            club_tz = club_timezones.get(row.club_name)
            timezone_suffix = f" ({club_tz})" if club_tz and club_tz != tz else ""
            lines.append(f"\n{row.club_name}{timezone_suffix}:")
        day = WEEKDAY_RU.get(row.weekday, row.weekday)
        status = "" if row.enabled else "  ⏸ выключено"
        days_before = getattr(row, "create_days_before", 0)
        create_day = " накануне" if days_before == 1 else (f" за {days_before} дн." if days_before else "")
        lines.append(f"  {day}: создание{create_day} {row.create_time}, игра {row.game_time}{status}")
        if row.reminder_time:
            lines.append(f"    напоминание: {row.reminder_time}")
        times = parse_import_times(row.import_times)
        if times:
            lines.append(f"    импорт: {', '.join(times)}")
    return "\n".join(lines)
