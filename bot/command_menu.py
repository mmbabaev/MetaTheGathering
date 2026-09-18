"""Role-aware Telegram command menus."""

from telegram import BotCommand, BotCommandScopeChat

from core.config import settings
from services.user import UserService

USER_COMMANDS = [
    BotCommand("tournaments", "Активные турниры и запись"),
    BotCommand("leaderboard", "Лидерборды Pauper"),
    BotCommand("social_rating", "Социальный рейтинг"),
    BotCommand("cellar", "Колоды из ячейки"),
    BotCommand("settings", "Настройки профиля"),
    BotCommand("help", "Справка по командам"),
]

SCOREKEEPER_COMMANDS = list(USER_COMMANDS)

POLL_COMMAND = BotCommand("poll", "Меню голосований: регуляры и рассылка")
CREATE_TOURNAMENT_COMMAND = BotCommand("create_tournament", "Создать турнир")
APP_STATS_COMMAND = BotCommand("app_statistics", "Статистика приложения (владелец)")
OWNER_COMMANDS = [APP_STATS_COMMAND]

ADMIN_COMMANDS = SCOREKEEPER_COMMANDS + [
    BotCommand("archive", "Архив закрытых турниров"),
    CREATE_TOURNAMENT_COMMAND,
    BotCommand("clubs", "Клубы и чаты объявлений"),
    BotCommand("delete_tournament", "Удалить турнир"),
    BotCommand("schedule", "Расписание автозаданий"),
    BotCommand("features", "Feature flags"),
    BotCommand("achievements", "Ачивки игрока"),
    BotCommand("bingo_preview", "Пример bingo-поля 4×4"),
    BotCommand("ranked_preseason", "Preseason-рейтинг Pauper"),
    POLL_COMMAND,
]


def commands_for_user(users: UserService, tg_id: int) -> list[BotCommand]:
    """Return the complete command menu for one current set of roles."""
    if users.is_admin(tg_id):
        commands = list(ADMIN_COMMANDS)
        if tg_id == settings.OWNER_CHAT_ID:
            commands.extend(OWNER_COMMANDS)
        return commands

    commands = list(USER_COMMANDS)
    if users.is_poll_organizer(tg_id):
        commands.append(POLL_COMMAND)
    if users.is_tournament_organizer(tg_id):
        commands.append(CREATE_TOURNAMENT_COMMAND)
    return commands


async def sync_user_command_menu(bot, users: UserService, tg_id: int) -> None:
    """Refresh one private chat menu, including newly granted or revoked roles."""
    await bot.set_my_commands(
        commands_for_user(users, tg_id),
        scope=BotCommandScopeChat(chat_id=tg_id),
    )
