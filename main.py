# Точка входа

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from telegram import Update as TGUpdate
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    PollAnswerHandler,
    filters,
)

from bot.keyboards import (
    CB_ADMIN_ARCH_MORE,
    CB_ADMIN_CUSTOM_ARCH,
    CB_ADMIN_MORE,
    CB_ADMIN_OPPONENTS,
    CB_ADMIN_PICK_ARCH,
    CB_ADMIN_SET_ARCH,
    CB_ADMIN_SHOW_FILLED,
    CB_AETHERHUB_CANCEL,
    CB_AETHERHUB_CONFIRM,
    CB_AETHERHUB_IMPORT,
    CB_ARCHETYPE,
    CB_ARCHETYPE_MORE,
    CB_BULK_ADD,
    CB_CLOSE_TOURNAMENT,
    CB_CREATE_POLL,
    CB_CUSTOM_ARCHETYPE,
    CB_DELETE_TOURNAMENT,
    CB_DELETE_TOURNAMENT_CANCEL,
    CB_DELETE_TOURNAMENT_CONFIRM,
    CB_EXPORT_EXCEL,
    CB_EXPORT_MENU,
    CB_EXPORT_PLAYERS,
    CB_FEATURE_INFO,
    CB_FEATURE_TOGGLE,
    CB_LEAVE,
    CB_LEAVE_CANCEL,
    CB_LEAVE_CONFIRM,
    CB_LINK_POLL_BY_URL,
    CB_NOTIFY_CANCEL,
    CB_NOTIFY_CONFIRM,
    CB_NOTIFY_NO_DECK,
    CB_PAY,
    CB_PAY_STATUS,
    CB_POLL_MENU,
    CB_REGISTER,
    CB_REVEAL_DECKS,
    CB_SET_IMPORT_TIME,
    CB_SETTINGS_NAME,
    CB_SETTINGS_TOGGLE_EMOJI,
    CB_TOURNAMENT,
    CB_TSTATUS,
)
from bot.scheduler import setup_scheduler
from bot.telegram import admin, common, player
from bot.telegram import aetherhub as aetherhub_handler
from bot.telegram import features as features_handler
from bot.telegram import payment as payment_handler
from bot.telegram import poll as poll_handler
from bot.telegram import settings as settings_handler
from core import models
from core.config import settings
from core.database import SessionLocal
from core.schemas import TournamentCreate
from services.feature_flags import FeatureFlagService
from services.tournament import TournamentService

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def _error_handler(update: object, context) -> None:
    logger.exception("Unhandled exception", exc_info=context.error)
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
    BotCommand("archive", "Архив закрытых турниров"),
    BotCommand("add_me", "Записать себя"),
    BotCommand("add_player", "Записать игрока"),
    BotCommand("add_players", "Массовая запись"),
    BotCommand("create_tournament", "Создать турнир"),
    BotCommand("delete_tournament", "Удалить турнир"),
    BotCommand("schedule", "Расписание автозаданий"),
    BotCommand("features", "Feature flags"),
]


async def _post_init(app: Application) -> None:
    db = SessionLocal()
    try:
        FeatureFlagService(db).ensure_defaults()
    finally:
        db.close()
    await _set_commands(app)


async def _set_commands(app: Application) -> None:
    # Обычным пользователям — только пользовательские команды
    await app.bot.set_my_commands(_USER_COMMANDS, scope=BotCommandScopeDefault())

    # Каждому известному админу — полный список в личном чате с ботом
    db = SessionLocal()
    try:
        db_admins = (
            db.execute(
                select(models.User.tg_id).where(
                    models.User.tg_id > 0,
                    (models.User.is_admin) | (models.User.is_superadmin),
                )
            )
            .scalars()
            .all()
        )
    finally:
        db.close()

    admin_ids = set(settings.admin_ids) | set(db_admins)
    for admin_id in admin_ids:
        try:
            await app.bot.set_my_commands(_ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:
            pass  # пользователь ещё не открывал чат с ботом

    logger.info(f"Bot commands registered. Admins with full menu: {admin_ids}")


def _debug_create_tournament() -> None:
    """Создаёт тестовый турнир для каждого chat_id из конфига. Только при DEBUG=true."""
    db = SessionLocal()
    try:
        svc = TournamentService(db)
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        for chat_id in settings.chat_ids:
            try:
                svc.create_tournament(
                    TournamentCreate(
                        title=f"[TEST] Pauper {date_str}",
                        chat_id=chat_id,
                        slug=None,
                    )
                )
                logger.info(f"[DEBUG] Created test tournament for chat {chat_id}")
            except Exception as e:
                logger.warning(f"[DEBUG] Could not create tournament for chat {chat_id}: {e}")
    finally:
        db.close()


def main() -> None:
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).post_init(_post_init).build()

    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("start", common.cmd_start, filters=private))
    app.add_handler(CommandHandler("help", common.cmd_help, filters=private))
    app.add_handler(CommandHandler("tournaments", player.cmd_tournaments, filters=private))
    app.add_handler(CommandHandler("settings", settings_handler.cmd_settings, filters=private))

    app.add_handler(CommandHandler("add_me", admin.cmd_add_me, filters=private))
    app.add_handler(CommandHandler("add_player", admin.cmd_add_player, filters=private))
    app.add_handler(CommandHandler("add_players", admin.cmd_add_players, filters=private))
    app.add_handler(CommandHandler("tournament_status", admin.cmd_tournament_status, filters=private))
    app.add_handler(CommandHandler("archive", admin.cmd_archive, filters=private))
    app.add_handler(CommandHandler("create_tournament", admin.cmd_create_tournament, filters=private))
    app.add_handler(CommandHandler("delete_tournament", admin.cmd_delete_tournament, filters=private))
    app.add_handler(CommandHandler("schedule", admin.cmd_schedule, filters=private))
    app.add_handler(CommandHandler("features", features_handler.cmd_features, filters=private))

    app.add_handler(CallbackQueryHandler(player.callback_tournament_select, pattern=f"^{CB_TOURNAMENT}:"))
    app.add_handler(CallbackQueryHandler(player.callback_register, pattern=f"^{CB_REGISTER}:"))
    app.add_handler(CallbackQueryHandler(player.callback_archetype, pattern=f"^{CB_ARCHETYPE}:"))
    app.add_handler(CallbackQueryHandler(player.callback_archetype_more, pattern=f"^{CB_ARCHETYPE_MORE}:"))
    app.add_handler(CallbackQueryHandler(player.callback_custom_archetype, pattern=f"^{CB_CUSTOM_ARCHETYPE}:"))
    app.add_handler(CallbackQueryHandler(player.callback_tournament_status, pattern=f"^{CB_TSTATUS}:"))
    app.add_handler(CallbackQueryHandler(player.callback_leave_tournament, pattern=f"^{CB_LEAVE}:"))
    app.add_handler(CallbackQueryHandler(player.callback_leave_confirm, pattern=f"^{CB_LEAVE_CONFIRM}:"))
    app.add_handler(CallbackQueryHandler(player.callback_leave_cancel, pattern=f"^{CB_LEAVE_CANCEL}:"))
    app.add_handler(CallbackQueryHandler(settings_handler.callback_settings_name, pattern=f"^{CB_SETTINGS_NAME}$"))
    app.add_handler(
        CallbackQueryHandler(settings_handler.callback_toggle_emoji, pattern=f"^{CB_SETTINGS_TOGGLE_EMOJI}$")
    )
    app.add_handler(CallbackQueryHandler(admin.callback_bulk_add_start, pattern=f"^{CB_BULK_ADD}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_pick_participant_arch, pattern=f"^{CB_ADMIN_PICK_ARCH}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_set_participant_arch, pattern=f"^{CB_ADMIN_SET_ARCH}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_pick_participant_arch_more, pattern=f"^{CB_ADMIN_ARCH_MORE}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_participant_custom_arch, pattern=f"^{CB_ADMIN_CUSTOM_ARCH}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_export_menu, pattern=f"^{CB_EXPORT_MENU}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_export_players, pattern=f"^{CB_EXPORT_PLAYERS}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_export_excel, pattern=f"^{CB_EXPORT_EXCEL}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_delete_tournament_prompt, pattern=f"^{CB_DELETE_TOURNAMENT}:"))
    app.add_handler(
        CallbackQueryHandler(admin.callback_delete_tournament_confirm, pattern=f"^{CB_DELETE_TOURNAMENT_CONFIRM}:")
    )
    app.add_handler(
        CallbackQueryHandler(admin.callback_delete_tournament_cancel, pattern=f"^{CB_DELETE_TOURNAMENT_CANCEL}:")
    )
    app.add_handler(CallbackQueryHandler(admin.callback_admin_show_filled, pattern=f"^{CB_ADMIN_SHOW_FILLED}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_reveal_decks, pattern=f"^{CB_REVEAL_DECKS}:"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_poll_menu, pattern=f"^{CB_POLL_MENU}:"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_link_poll_prompt, pattern=f"^{CB_LINK_POLL_BY_URL}:"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_create_poll, pattern=f"^{CB_CREATE_POLL}:"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_notify_no_deck, pattern=f"^{CB_NOTIFY_NO_DECK}:"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_notify_confirm, pattern=f"^{CB_NOTIFY_CONFIRM}:"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_notify_cancel, pattern=f"^{CB_NOTIFY_CANCEL}:"))
    app.add_handler(
        CallbackQueryHandler(aetherhub_handler.callback_aetherhub_import_prompt, pattern=f"^{CB_AETHERHUB_IMPORT}:")
    )
    app.add_handler(
        CallbackQueryHandler(aetherhub_handler.callback_aetherhub_confirm, pattern=f"^{CB_AETHERHUB_CONFIRM}:")
    )
    app.add_handler(
        CallbackQueryHandler(aetherhub_handler.callback_aetherhub_cancel, pattern=f"^{CB_AETHERHUB_CANCEL}:")
    )
    app.add_handler(CallbackQueryHandler(aetherhub_handler.callback_set_import_time, pattern=f"^{CB_SET_IMPORT_TIME}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_admin_more, pattern=f"^{CB_ADMIN_MORE}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_close_tournament, pattern=f"^{CB_CLOSE_TOURNAMENT}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_fill_opponents, pattern=f"^{CB_ADMIN_OPPONENTS}:"))
    app.add_handler(CallbackQueryHandler(features_handler.callback_feature_info, pattern=f"^{CB_FEATURE_INFO}:"))
    app.add_handler(CallbackQueryHandler(features_handler.callback_feature_toggle, pattern=f"^{CB_FEATURE_TOGGLE}:"))
    app.add_handler(CallbackQueryHandler(payment_handler.callback_pay, pattern=f"^{CB_PAY}:"))
    app.add_handler(CallbackQueryHandler(payment_handler.callback_pay_status, pattern=f"^{CB_PAY_STATUS}:"))
    app.add_handler(PollAnswerHandler(poll_handler.handle_poll_answer))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & private, player.message_text_input))

    app.add_error_handler(_error_handler)

    setup_scheduler(app)

    logger.info("Bot starting (polling)...")
    app.run_polling(allowed_updates=["message", "callback_query", "poll_answer"])


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
