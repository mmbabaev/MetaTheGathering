# Шаблоны сообщений

NO_ACTIVE_TOURNAMENTS = "Нет активных турниров."
CHOOSE_ARCHETYPE = "Выберите архетип колоды:"
CUSTOM_ARCHETYPE_PROMPT = "Напишите название архетипа:"
REGISTERED_AS = "Вы записаны как {archetype_name}."
REGISTERED = "Вы записаны."
ALREADY_REGISTERED = "Вы уже записаны на этот турнир."
REGISTRATION_CLOSED = "Регистрация на этот турнир закрыта."
TOURNAMENT_NOT_FOUND = "Турнир не найден."
LEAVE_CONFIRM_PROMPT = "Вы уверены, что хотите выйти из турнира?"
LEFT_TOURNAMENT = "Вы вышли из турнира."
NOT_REGISTERED_IN_TOURNAMENT = "Вы не записаны на этот турнир."


# Name prompts
ASK_NAME = "Как вас зовут? Введите имя (или имя и фамилию через пробел):"
NAME_SAVED = "Имя сохранено: {full_name}"
NAME_REQUIRED_FOR_REGISTRATION = "Для записи на турнир нужно указать ваше имя.\n\nКак вас зовут? Введите имя (или имя и фамилию через пробел):"

# Settings
SETTINGS_MENU = "⚙️ Настройки"
SETTINGS_CHANGE_NAME_PROMPT = "Введите новое имя (или имя и фамилию через пробел):"

# Admin messages
NOT_ADMIN = "У вас нет прав администратора."
NO_DECK_NAME = "Укажите название колоды. Пример: /add_me Burn"
NO_ACTIVE_TOURNAMENT = "Нет активного турнира в этом чате."
PLAYER_ADDED = "✅ {user} добавлен как {archetype_name}."
TELEGRAM_USER_LOOKUP_FAILED = "Не удалось найти @{username} в Telegram. Проверьте @username."
TOURNAMENT_CLOSED_MSG = "Турнир закрыт."
MULTIPLE_TOURNAMENTS_MSG = "Активных турниров несколько. Используйте /tournament_status чтобы увидеть их ID."
ADD_PLAYERS_USAGE = (
    "Формат:\n/add_players\n@username1 Название колоды\n@username2 Другая колода"
)
BULK_ADD_PROMPT = (
    "Введите список игроков — по одному на строке (Имя Фамилия):\n\n"
    "Пример:\nИван Иванов\nМария Петрова\nАлексей"
)
BULK_ADD_EMPTY = "Список игроков пустой."
PARTICIPANT_NOT_FOUND = "Участник не найден."
ADMIN_ARCH_SAVED = "✅ Колода обновлена: {archetype_name}"
DECKS_REVEALED = "👁 Колоды участников теперь видны всем."


HELP_TEXT = """\
Команды для игроков:
/tournaments — список активных турниров и запись
/settings — настройки профиля (имя)

Команды для администраторов:
/tournament_status — участники всех активных турниров
/add_me <колода> — записать себя на турнир
/add_player @username <колода> — записать игрока
/add_players — массовая запись (по строке: @username Колода)
/close_tournament — закрыть текущий турнир\
"""


def _participant_icon(p) -> str:
    """✅ колода указана / ⬜ колоды нет."""
    return "✅" if p.archetype else "⬜"


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


def format_tournament_status(
    title: str, status: str, participants: list, decks_hidden: bool = False
) -> str:
    """Структурированный список участников турнира."""
    total = len(participants)
    with_deck = sum(1 for p in participants if p.archetype)
    without = total - with_deck

    header = f"🏆 {title} · {status} · {total} чел."
    if total:
        header += f"\n✅ {with_deck} с колодой  ⬜ {without} без"

    lines = [header, ""]
    for p in participants:
        icon = _participant_icon(p)
        if p.user:
            name_parts = [n for n in (p.user.last_name, p.user.first_name) if n]
            full_name = " ".join(name_parts) if name_parts else f"id{p.user.tg_id}"
            username_hint = f" (@{p.user.username})" if p.user.username else ""
            display = f"{full_name}{username_hint}"
        else:
            display = "?"
        if p.archetype:
            archetype = "▓▓▓" if decks_hidden else p.archetype.name
        else:
            archetype = "не указана"
        lines.append(f"{icon} {display} — {archetype}")
    return "\n".join(lines)
