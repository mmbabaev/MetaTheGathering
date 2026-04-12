# Шаблоны сообщений

NO_ACTIVE_TOURNAMENTS = "Нет активных турниров."
CHOOSE_ARCHETYPE = "Выберите архетип колоды:"
CUSTOM_ARCHETYPE_PROMPT = "Напишите название архетипа:"
REGISTERED_AS = "Вы записаны как {archetype_name}."
REGISTERED = "Вы записаны."
ALREADY_REGISTERED = "Вы уже записаны на этот турнир."
REGISTRATION_CLOSED = "Регистрация на этот турнир закрыта."
TOURNAMENT_NOT_FOUND = "Турнир не найден."


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
