# Точка входа

import asyncio
import logging

from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    PollAnswerHandler,
    filters,
)

from core.config import settings
from core.database import SessionLocal
from core.schemas import TournamentCreate
from services.tournament import TournamentService
from bot.telegram import common, player, admin, poll as poll_handler
from bot.telegram import settings as settings_handler
from bot.keyboards import (
    CB_TOURNAMENT, CB_REGISTER, CB_ARCHETYPE, CB_CUSTOM_ARCHETYPE,
    CB_ARCHETYPE_MORE,
    CB_SETTINGS_NAME, CB_TSTATUS, CB_LEAVE, CB_LEAVE_CONFIRM, CB_LEAVE_CANCEL,
    CB_BULK_ADD, CB_ADMIN_PICK_ARCH, CB_ADMIN_SET_ARCH, CB_ADMIN_CUSTOM_ARCH,
    CB_ADMIN_ARCH_MORE, CB_EXPORT_EXCEL,
    CB_DELETE_TOURNAMENT, CB_DELETE_TOURNAMENT_CONFIRM, CB_DELETE_TOURNAMENT_CANCEL,
    CB_ADMIN_SHOW_FILLED,
    CB_REVEAL_DECKS,
    CB_POLL_MENU,
    CB_CREATE_POLL,
    CB_NOTIFY_NO_DECK,
    CB_NOTIFY_CONFIRM,
    CB_NOTIFY_CANCEL,
)
from bot.scheduler import setup_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _error_handler(update: object, context) -> None:
    logger.exception("Unhandled exception", exc_info=context.error)
    from telegram import Update as TGUpdate
    if isinstance(update, TGUpdate) and update.effective_message:
        try:
            await update.effective_message.reply_text("⚠️ Внутренняя ошибка. Попробуйте ещё раз.")
        except Exception:
            pass

if settings.DEBUG:
    logging.getLogger("services.tournament").setLevel(logging.DEBUG)


_USER_COMMANDS = [
    BotCommand("tournaments", "Активные турниры и запись"),
    BotCommand("settings", "Настройки профиля"),
    BotCommand("help", "Справка по командам"),
]

_ADMIN_COMMANDS = _USER_COMMANDS + [
    BotCommand("tournament_status", "Участники турниров"),
    BotCommand("add_me", "Записать себя"),
    BotCommand("add_player", "Записать игрока"),
    BotCommand("add_players", "Массовая запись"),
    BotCommand("close_tournament", "Закрыть турнир"),
    BotCommand("create_tournament", "Создать турнир"),
    BotCommand("delete_tournament", "Удалить турнир"),
]


async def _set_commands(app: Application) -> None:
    # Обычным пользователям — только пользовательские команды
    await app.bot.set_my_commands(_USER_COMMANDS, scope=BotCommandScopeDefault())

    # Каждому известному админу — полный список в личном чате с ботом
    from core.database import SessionLocal as SL
    from sqlalchemy import select
    from core import models
    db = SL()
    try:
        db_admins = db.execute(
            select(models.User.tg_id).where(
                models.User.tg_id > 0,
                (models.User.is_admin == True) | (models.User.is_superadmin == True),
            )
        ).scalars().all()
    finally:
        db.close()

    admin_ids = set(settings.admin_ids) | set(db_admins)
    for admin_id in admin_ids:
        try:
            await app.bot.set_my_commands(
                _ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id)
            )
        except Exception:
            pass  # пользователь ещё не открывал чат с ботом

    logger.info(f"Bot commands registered. Admins with full menu: {admin_ids}")


def _debug_create_tournament() -> None:
    """Создаёт тестовый турнир для каждого chat_id из конфига. Только при DEBUG=true."""
    from datetime import datetime
    db = SessionLocal()
    try:
        svc = TournamentService(db)
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        for chat_id in settings.chat_ids:
            try:
                svc.create_tournament(TournamentCreate(
                    title=f"[TEST] Pauper {date_str}",
                    chat_id=chat_id,
                    slug=None,
                ))
                logger.info(f"[DEBUG] Created test tournament for chat {chat_id}")
            except Exception as e:
                logger.warning(f"[DEBUG] Could not create tournament for chat {chat_id}: {e}")
    finally:
        db.close()


def main() -> None:
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).post_init(_set_commands).build()

    app.add_handler(CommandHandler("start", common.cmd_start))
    app.add_handler(CommandHandler("help", common.cmd_help))
    app.add_handler(CommandHandler("tournaments", player.cmd_tournaments))
    app.add_handler(CommandHandler("settings", settings_handler.cmd_settings))

    app.add_handler(CommandHandler("add_me", admin.cmd_add_me))
    app.add_handler(CommandHandler("add_player", admin.cmd_add_player))
    app.add_handler(CommandHandler("add_players", admin.cmd_add_players))
    app.add_handler(CommandHandler("tournament_status", admin.cmd_tournament_status))
    app.add_handler(CommandHandler("close_tournament", admin.cmd_close_tournament))
    app.add_handler(CommandHandler("create_tournament", admin.cmd_create_tournament))
    app.add_handler(CommandHandler("delete_tournament", admin.cmd_delete_tournament))

    app.add_handler(
        CallbackQueryHandler(player.callback_tournament_select, pattern=f"^{CB_TOURNAMENT}:")
    )
    app.add_handler(
        CallbackQueryHandler(player.callback_register, pattern=f"^{CB_REGISTER}:")
    )
    app.add_handler(
        CallbackQueryHandler(player.callback_archetype, pattern=f"^{CB_ARCHETYPE}:")
    )
    app.add_handler(
        CallbackQueryHandler(player.callback_archetype_more, pattern=f"^{CB_ARCHETYPE_MORE}:")
    )
    app.add_handler(
        CallbackQueryHandler(player.callback_custom_archetype, pattern=f"^{CB_CUSTOM_ARCHETYPE}:")
    )
    app.add_handler(
        CallbackQueryHandler(player.callback_tournament_status, pattern=f"^{CB_TSTATUS}:")
    )
    app.add_handler(
        CallbackQueryHandler(player.callback_leave_tournament, pattern=f"^{CB_LEAVE}:")
    )
    app.add_handler(
        CallbackQueryHandler(player.callback_leave_confirm, pattern=f"^{CB_LEAVE_CONFIRM}:")
    )
    app.add_handler(
        CallbackQueryHandler(player.callback_leave_cancel, pattern=f"^{CB_LEAVE_CANCEL}:")
    )
    app.add_handler(
        CallbackQueryHandler(settings_handler.callback_settings_name, pattern=f"^{CB_SETTINGS_NAME}$")
    )
    app.add_handler(
        CallbackQueryHandler(admin.callback_bulk_add_start, pattern=f"^{CB_BULK_ADD}:")
    )
    app.add_handler(
        CallbackQueryHandler(admin.callback_admin_pick_arch, pattern=f"^{CB_ADMIN_PICK_ARCH}:")
    )
    app.add_handler(
        CallbackQueryHandler(admin.callback_admin_set_arch, pattern=f"^{CB_ADMIN_SET_ARCH}:")
    )
    app.add_handler(
        CallbackQueryHandler(admin.callback_admin_arch_more, pattern=f"^{CB_ADMIN_ARCH_MORE}:")
    )
    app.add_handler(
        CallbackQueryHandler(admin.callback_admin_custom_arch, pattern=f"^{CB_ADMIN_CUSTOM_ARCH}:")
    )
    app.add_handler(
        CallbackQueryHandler(admin.callback_export_excel, pattern=f"^{CB_EXPORT_EXCEL}:")
    )
    app.add_handler(
        CallbackQueryHandler(admin.callback_delete_tournament_prompt, pattern=f"^{CB_DELETE_TOURNAMENT}:")
    )
    app.add_handler(
        CallbackQueryHandler(admin.callback_delete_tournament_confirm, pattern=f"^{CB_DELETE_TOURNAMENT_CONFIRM}:")
    )
    app.add_handler(
        CallbackQueryHandler(admin.callback_delete_tournament_cancel, pattern=f"^{CB_DELETE_TOURNAMENT_CANCEL}:")
    )
    app.add_handler(
        CallbackQueryHandler(admin.callback_admin_show_filled, pattern=f"^{CB_ADMIN_SHOW_FILLED}:")
    )
    app.add_handler(
        CallbackQueryHandler(admin.callback_reveal_decks, pattern=f"^{CB_REVEAL_DECKS}:")
    )
    app.add_handler(
        CallbackQueryHandler(poll_handler.callback_poll_menu, pattern=f"^{CB_POLL_MENU}:"),
        CallbackQueryHandler(poll_handler.callback_create_poll, pattern=f"^{CB_CREATE_POLL}:")
    )
    app.add_handler(
        CallbackQueryHandler(poll_handler.callback_notify_no_deck, pattern=f"^{CB_NOTIFY_NO_DECK}:")
    )
    app.add_handler(
        CallbackQueryHandler(poll_handler.callback_notify_confirm, pattern=f"^{CB_NOTIFY_CONFIRM}:")
    )
    app.add_handler(
        CallbackQueryHandler(poll_handler.callback_notify_cancel, pattern=f"^{CB_NOTIFY_CANCEL}:")
    )
    app.add_handler(PollAnswerHandler(poll_handler.handle_poll_answer))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, player.message_text_input)
    )

    app.add_error_handler(_error_handler)

    setup_scheduler(app)

    if settings.DEBUG:
        _debug_create_tournament()

    logger.info("Bot starting (polling)...")
    app.run_polling(allowed_updates=["message", "callback_query", "poll_answer"])


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
