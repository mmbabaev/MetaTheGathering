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
PLAYER_NOT_FOUND = "Пользователь @{username} не найден. Он должен написать боту /start."
PLAYER_ADDED = "✅ @{username} добавлен как {archetype_name}."
TOURNAMENT_CLOSED_MSG = "Турнир закрыт."
ADD_PLAYERS_USAGE = (
    "Формат:\n/add_players\n@username1 Название колоды\n@username2 Другая колода"
)


def format_tournament_card(title: str, status: str, slug: str | None = None) -> str:
    parts = [f"Турнир: {title}", f"Статус: {status}"]
    if slug:
        parts.append(f"Slug: {slug}")
    return "\n".join(parts)
