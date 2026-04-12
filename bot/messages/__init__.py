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


def format_tournament_card(title: str, status: str, slug: str | None = None) -> str:
    parts = [f"Турнир: {title}", f"Статус: {status}"]
    if slug:
        parts.append(f"Slug: {slug}")
    return "\n".join(parts)


def format_tournament_status(title: str, status: str, participants: list) -> str:
    """Форматирует список участников турнира для отображения игрокам."""
    lines = [
        f"Турнир: {title}",
        f"Статус: {status}",
        f"Участники ({len(participants)}):",
    ]
    for i, p in enumerate(participants, 1):
        if p.user:
            name_parts = [n for n in (p.user.first_name, p.user.last_name) if n]
            full_name = " ".join(name_parts) if name_parts else f"id{p.user.tg_id}"
            username_hint = f" (@{p.user.username})" if p.user.username else ""
            display = f"{full_name}{username_hint}"
        else:
            display = "?"
        archetype = p.archetype.name if p.archetype else "не указана"
        confirmed = " ✅" if p.confirmed else ""
        lines.append(f"{i}. {display} — {archetype}{confirmed}")
    return "\n".join(lines)
