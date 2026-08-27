# Точка входа

import asyncio
import logging
from collections.abc import Awaitable, Callable
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
from telegram.request import BaseRequest

from bot.keyboards import (
    CB_ADMIN_ARCH_MORE,
    CB_ADMIN_CUSTOM_ARCH,
    CB_ADMIN_IMPORT_META,
    CB_ADMIN_MORE,
    CB_ADMIN_OPPONENTS,
    CB_ADMIN_PICK_ARCH,
    CB_ADMIN_PLAYER_ACTIONS,
    CB_ADMIN_REMOVE_CONFIRM,
    CB_ADMIN_REMOVE_DO,
    CB_ADMIN_SET_ARCH,
    CB_ADMIN_SHOW_FILLED,
    CB_ADMIN_SHOW_OPPONENTS,
    CB_ADMIN_TOGGLE_POLL_ORGANIZER,
    CB_ADMIN_TOGGLE_SCOREKEEPER,
    CB_AETHERHUB_CANCEL,
    CB_AETHERHUB_CONFIRM,
    CB_AETHERHUB_IMPORT,
    CB_APP_STATS_HOME,
    CB_APP_STATS_NOTIFY_ROUNDS,
    CB_ARCHETYPE,
    CB_ARCHETYPE_MORE,
    CB_BULK_ADD,
    CB_CELLAR_CANCEL,
    CB_CELLAR_CANCEL_CONFIRM,
    CB_CELLAR_DATE,
    CB_CELLAR_DATES,
    CB_CELLAR_DECK,
    CB_CELLAR_NOOP,
    CB_CELLAR_RESERVE,
    CB_CLOSE_TOURNAMENT,
    CB_CREATE_POLL,
    CB_CUSTOM_ARCHETYPE,
    CB_DEBUG_ROUND_NOTIFY,
    CB_DEFER_DECK,
    CB_DELETE_TOURNAMENT,
    CB_DELETE_TOURNAMENT_CANCEL,
    CB_DELETE_TOURNAMENT_CONFIRM,
    CB_EXPORT_EXCEL,
    CB_EXPORT_MENU,
    CB_EXPORT_PLAYERS,
    CB_FEATURE_INFO,
    CB_FEATURE_TOGGLE,
    CB_FILL_MISSING_CUSTOM,
    CB_FILL_MISSING_MORE,
    CB_FILL_MISSING_PICK,
    CB_FILL_MISSING_SET,
    CB_HIDE_DECKS,
    CB_LEAVE,
    CB_LEAVE_CANCEL,
    CB_LEAVE_CONFIRM,
    CB_LINK_POLL_BY_URL,
    CB_META_CHART,
    CB_NOTIFY_CANCEL,
    CB_NOTIFY_CONFIRM,
    CB_NOTIFY_NO_DECK,
    CB_PAY,
    CB_PAY_STATUS,
    CB_POLL_BROADCAST,
    CB_POLL_BROADCAST_CANCEL,
    CB_POLL_CLUB,
    CB_POLL_MENU,
    CB_POLL_ORG_MENU,
    CB_POLL_PING,
    CB_POLL_REGULAR_TOGGLE,
    CB_POLL_REGULARS,
    CB_REGISTER,
    CB_REOPEN_TOURNAMENT,
    CB_REVEAL_DECKS,
    CB_REVEAL_DECKS_CANCEL,
    CB_REVEAL_DECKS_CONFIRM,
    CB_SCHEDULE_EDIT_FIELD,
    CB_SCHEDULE_IMPORTS,
    CB_SCHEDULE_LIST,
    CB_SCHEDULE_ROW,
    CB_SCHEDULE_SET_WEEKDAY,
    CB_SCHEDULE_TOGGLE,
    CB_SCHEDULE_WEEKDAY,
    CB_SET_IMPORT_TIME,
    CB_SETTINGS_NAME,
    CB_SETTINGS_TOGGLE_ACHIEVEMENTS_NOTIFY,
    CB_SETTINGS_TOGGLE_CELLAR_NOTIFY,
    CB_SETTINGS_TOGGLE_EMOJI,
    CB_SETTINGS_TOGGLE_OPPONENT_NOTIFY,
    CB_SETTINGS_TOGGLE_POLL_NOTIFY,
    CB_SETTINGS_TOGGLE_STATUS_PAIRINGS,
    CB_STANDINGS,
    CB_TOURNAMENT,
    CB_TSTATUS,
)
from bot.scheduler import setup_scheduler
from bot.telegram import achievements as achievements_handler
from bot.telegram import admin, common, player
from bot.telegram import aetherhub as aetherhub_handler
from bot.telegram import app_stats as app_stats_handler
from bot.telegram import bingo as bingo_handler
from bot.telegram import cellar as cellar_handler
from bot.telegram import features as features_handler
from bot.telegram import payment as payment_handler
from bot.telegram import poll as poll_handler
from bot.telegram import rating as rating_handler
from bot.telegram import schedule as schedule_handler
from bot.telegram import settings as settings_handler
from core import models
from core.config import settings
from core.database import SessionLocal
from core.schemas import TournamentCreate
from services.cellar import CellarService
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.schedule import ScheduleService
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
    BotCommand("social_rating", "Социальный рейтинг"),
    BotCommand("cellar", "Колоды из ячейки"),
    BotCommand("settings", "Настройки профиля"),
    BotCommand("help", "Справка по командам"),
]

_SCOREKEEPER_COMMANDS = _USER_COMMANDS + [
    BotCommand("tournament_status", "Участники турниров"),
    BotCommand("add_players", "Массовая запись"),
]

_POLL_CMD = BotCommand("poll", "Меню голосований: регуляры и рассылка")
_APP_STATS_CMD = BotCommand("app_statistics", "Статистика приложения (владелец)")

_ADMIN_COMMANDS = _SCOREKEEPER_COMMANDS + [
    BotCommand("archive", "Архив закрытых турниров"),
    BotCommand("create_tournament", "Создать турнир"),
    BotCommand("delete_tournament", "Удалить турнир"),
    BotCommand("schedule", "Расписание автозаданий"),
    BotCommand("features", "Feature flags"),
    BotCommand("achievements", "Ачивки игрока"),
    BotCommand("bingo_preview", "Пример bingo-поля 4×4"),
    _POLL_CMD,
]


async def _post_init(app: Application) -> None:
    db = SessionLocal()
    try:
        FeatureFlagService(db).ensure_defaults()
        created = ScheduleService(db).ensure_defaults()
        if created:
            logger.info("Расписание засеяно из кода: %s строк", created)
        if FeatureFlagService(db).is_enabled(FeatureFlags.CELLAR_DECKS):
            cellar_sync = CellarService(db).ensure_catalog()
            if cellar_sync:
                logger.info(
                    "Каталог колод из ячейки синхронизирован: created=%s updated=%s deactivated=%s",
                    *cellar_sync,
                )
    finally:
        db.close()
    await _set_commands(app)


async def _set_commands(app: Application) -> None:
    # Обычным пользователям — только пользовательские команды
    await app.bot.set_my_commands(_USER_COMMANDS, scope=BotCommandScopeDefault())

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
        db_scorekeepers = (
            db.execute(
                select(models.User.tg_id).where(
                    models.User.tg_id > 0,
                    models.User.is_scorekeeper == True,  # noqa: E712
                )
            )
            .scalars()
            .all()
        )
        db_organizers = (
            db.execute(
                select(models.User.tg_id).where(
                    models.User.tg_id > 0,
                    models.User.is_poll_organizer == True,  # noqa: E712
                )
            )
            .scalars()
            .all()
        )
    finally:
        db.close()

    admin_ids = set(settings.admin_ids) | set(db_admins)
    organizer_ids = set(db_organizers) - admin_ids  # у админов /poll уже есть
    scorekeeper_ids = set(db_scorekeepers) - admin_ids

    owner_id = settings.OWNER_CHAT_ID
    for admin_id in admin_ids:
        # Владельцу — те же админ-команды плюс /app_statistics (статистика приложения).
        cmds = _ADMIN_COMMANDS + [_APP_STATS_CMD] if admin_id == owner_id else _ADMIN_COMMANDS
        try:
            await app.bot.set_my_commands(cmds, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:
            pass

    for sk_id in scorekeeper_ids:
        cmds = _SCOREKEEPER_COMMANDS + ([_POLL_CMD] if sk_id in organizer_ids else [])
        try:
            await app.bot.set_my_commands(cmds, scope=BotCommandScopeChat(chat_id=sk_id))
        except Exception:
            pass

    # Чистые организаторы голосований (не админ, не метаписец) — пользовательские команды + /poll
    for org_id in organizer_ids - scorekeeper_ids:
        try:
            await app.bot.set_my_commands(_USER_COMMANDS + [_POLL_CMD], scope=BotCommandScopeChat(chat_id=org_id))
        except Exception:
            pass

    logger.info(
        f"Bot commands registered. Admins: {admin_ids}, Scorekeepers: {scorekeeper_ids}, Organizers: {organizer_ids}"
    )


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


def build_application(
    *,
    token: str | None = None,
    request: BaseRequest | None = None,
    enable_scheduler: bool = True,
    post_init: Callable[[Application], Awaitable[None]] | None = _post_init,
) -> Application:
    """Build the PTB application without starting polling.

    Tests can inject a recording Bot API request and disable background jobs. Production
    keeps the same defaults and calls :meth:`Application.run_polling` in ``main``.
    """
    builder = Application.builder().token(token or settings.TELEGRAM_BOT_TOKEN)
    if post_init is not None:
        builder = builder.post_init(post_init)
    if request is not None:
        builder = builder.request(request)
    elif settings.TELEGRAM_PROXY_URL:
        builder = builder.proxy(settings.TELEGRAM_PROXY_URL).get_updates_proxy(settings.TELEGRAM_PROXY_URL)
    app = builder.build()

    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("start", common.cmd_start, filters=private))
    app.add_handler(CommandHandler("help", common.cmd_help, filters=private))
    app.add_handler(CommandHandler("tournaments", player.cmd_tournaments, filters=private))
    app.add_handler(CommandHandler("social_rating", rating_handler.cmd_social_rating, filters=private))
    app.add_handler(CommandHandler("cellar", cellar_handler.cmd_cellar, filters=private))
    app.add_handler(CommandHandler("settings", settings_handler.cmd_settings, filters=private))
    app.add_handler(CommandHandler("poll", poll_handler.cmd_poll, filters=private))
    app.add_handler(CommandHandler("app_statistics", app_stats_handler.cmd_app_statistics, filters=private))
    app.add_handler(CommandHandler("achievements", achievements_handler.cmd_achievements, filters=private))
    app.add_handler(CommandHandler("bingo_preview", bingo_handler.cmd_bingo_preview, filters=private))

    app.add_handler(CommandHandler("add_players", admin.cmd_add_players, filters=private))
    app.add_handler(CommandHandler("tournament_status", admin.cmd_tournament_status, filters=private))
    app.add_handler(CommandHandler("archive", admin.cmd_archive, filters=private))
    app.add_handler(CommandHandler("create_tournament", admin.cmd_create_tournament, filters=private))
    app.add_handler(CommandHandler("delete_tournament", admin.cmd_delete_tournament, filters=private))
    app.add_handler(CommandHandler("schedule", schedule_handler.cmd_schedule, filters=private))
    app.add_handler(CommandHandler("features", features_handler.cmd_features, filters=private))

    app.add_handler(CallbackQueryHandler(cellar_handler.callback_dates, pattern=f"^{CB_CELLAR_DATES}$"))
    app.add_handler(CallbackQueryHandler(cellar_handler.callback_date, pattern=f"^{CB_CELLAR_DATE}:"))
    app.add_handler(CallbackQueryHandler(cellar_handler.callback_deck, pattern=f"^{CB_CELLAR_DECK}:"))
    app.add_handler(CallbackQueryHandler(cellar_handler.callback_reserve, pattern=f"^{CB_CELLAR_RESERVE}:"))
    app.add_handler(CallbackQueryHandler(cellar_handler.callback_cancel_prompt, pattern=f"^{CB_CELLAR_CANCEL}:"))
    app.add_handler(
        CallbackQueryHandler(cellar_handler.callback_cancel_confirm, pattern=f"^{CB_CELLAR_CANCEL_CONFIRM}:")
    )
    app.add_handler(CallbackQueryHandler(cellar_handler.callback_noop, pattern=f"^{CB_CELLAR_NOOP}$"))

    app.add_handler(CallbackQueryHandler(player.callback_tournament_select, pattern=f"^{CB_TOURNAMENT}:"))
    app.add_handler(CallbackQueryHandler(player.callback_register, pattern=f"^{CB_REGISTER}:"))
    app.add_handler(CallbackQueryHandler(player.callback_archetype, pattern=f"^{CB_ARCHETYPE}:"))
    app.add_handler(CallbackQueryHandler(player.callback_defer_deck, pattern=f"^{CB_DEFER_DECK}:"))
    app.add_handler(CallbackQueryHandler(player.callback_archetype_more, pattern=f"^{CB_ARCHETYPE_MORE}:"))
    app.add_handler(CallbackQueryHandler(player.callback_custom_archetype, pattern=f"^{CB_CUSTOM_ARCHETYPE}:"))
    app.add_handler(CallbackQueryHandler(player.callback_pick_missing_deck, pattern=f"^{CB_FILL_MISSING_PICK}:"))
    app.add_handler(CallbackQueryHandler(player.callback_set_missing_deck, pattern=f"^{CB_FILL_MISSING_SET}:"))
    app.add_handler(CallbackQueryHandler(player.callback_missing_deck_more, pattern=f"^{CB_FILL_MISSING_MORE}:"))
    app.add_handler(CallbackQueryHandler(player.callback_missing_custom_deck, pattern=f"^{CB_FILL_MISSING_CUSTOM}:"))
    app.add_handler(CallbackQueryHandler(player.callback_tournament_status, pattern=f"^{CB_TSTATUS}:"))
    app.add_handler(CallbackQueryHandler(player.callback_leave_tournament, pattern=f"^{CB_LEAVE}:"))
    app.add_handler(CallbackQueryHandler(player.callback_leave_confirm, pattern=f"^{CB_LEAVE_CONFIRM}:"))
    app.add_handler(CallbackQueryHandler(player.callback_leave_cancel, pattern=f"^{CB_LEAVE_CANCEL}:"))
    app.add_handler(CallbackQueryHandler(settings_handler.callback_settings_name, pattern=f"^{CB_SETTINGS_NAME}$"))
    app.add_handler(
        CallbackQueryHandler(settings_handler.callback_toggle_emoji, pattern=f"^{CB_SETTINGS_TOGGLE_EMOJI}$")
    )
    app.add_handler(
        CallbackQueryHandler(
            settings_handler.callback_toggle_achievements_notify,
            pattern=f"^{CB_SETTINGS_TOGGLE_ACHIEVEMENTS_NOTIFY}$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            settings_handler.callback_toggle_opponent_notify, pattern=f"^{CB_SETTINGS_TOGGLE_OPPONENT_NOTIFY}$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            settings_handler.callback_toggle_poll_notify, pattern=f"^{CB_SETTINGS_TOGGLE_POLL_NOTIFY}$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            settings_handler.callback_toggle_cellar_notify, pattern=f"^{CB_SETTINGS_TOGGLE_CELLAR_NOTIFY}$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            settings_handler.callback_toggle_status_pairings, pattern=f"^{CB_SETTINGS_TOGGLE_STATUS_PAIRINGS}$"
        )
    )
    app.add_handler(CallbackQueryHandler(admin.callback_bulk_add_start, pattern=f"^{CB_BULK_ADD}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_meta_import_start, pattern=f"^{CB_ADMIN_IMPORT_META}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_pick_participant_arch, pattern=f"^{CB_ADMIN_PICK_ARCH}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_set_participant_arch, pattern=f"^{CB_ADMIN_SET_ARCH}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_pick_participant_arch_more, pattern=f"^{CB_ADMIN_ARCH_MORE}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_participant_custom_arch, pattern=f"^{CB_ADMIN_CUSTOM_ARCH}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_export_menu, pattern=f"^{CB_EXPORT_MENU}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_export_players, pattern=f"^{CB_EXPORT_PLAYERS}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_export_excel, pattern=f"^{CB_EXPORT_EXCEL}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_meta_chart, pattern=f"^{CB_META_CHART}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_standings, pattern=f"^{CB_STANDINGS}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_delete_tournament_prompt, pattern=f"^{CB_DELETE_TOURNAMENT}:"))
    app.add_handler(
        CallbackQueryHandler(admin.callback_delete_tournament_confirm, pattern=f"^{CB_DELETE_TOURNAMENT_CONFIRM}:")
    )
    app.add_handler(
        CallbackQueryHandler(admin.callback_delete_tournament_cancel, pattern=f"^{CB_DELETE_TOURNAMENT_CANCEL}:")
    )
    app.add_handler(CallbackQueryHandler(admin.callback_admin_show_filled, pattern=f"^{CB_ADMIN_SHOW_FILLED}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_admin_player_actions, pattern=f"^{CB_ADMIN_PLAYER_ACTIONS}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_admin_show_opponents, pattern=f"^{CB_ADMIN_SHOW_OPPONENTS}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_admin_remove_confirm, pattern=f"^{CB_ADMIN_REMOVE_CONFIRM}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_admin_remove_do, pattern=f"^{CB_ADMIN_REMOVE_DO}:"))
    app.add_handler(
        CallbackQueryHandler(admin.callback_admin_toggle_scorekeeper, pattern=f"^{CB_ADMIN_TOGGLE_SCOREKEEPER}:")
    )
    app.add_handler(
        CallbackQueryHandler(admin.callback_admin_toggle_poll_organizer, pattern=f"^{CB_ADMIN_TOGGLE_POLL_ORGANIZER}:")
    )
    app.add_handler(CallbackQueryHandler(admin.callback_reveal_decks, pattern=f"^{CB_REVEAL_DECKS}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_reveal_decks_confirm, pattern=f"^{CB_REVEAL_DECKS_CONFIRM}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_reveal_decks_cancel, pattern=f"^{CB_REVEAL_DECKS_CANCEL}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_hide_decks, pattern=f"^{CB_HIDE_DECKS}:"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_poll_menu, pattern=f"^{CB_POLL_MENU}:"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_link_poll_prompt, pattern=f"^{CB_LINK_POLL_BY_URL}:"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_create_poll, pattern=f"^{CB_CREATE_POLL}:"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_poll_broadcast, pattern=f"^{CB_POLL_BROADCAST}:"))
    app.add_handler(
        CallbackQueryHandler(poll_handler.callback_poll_broadcast_cancel, pattern=f"^{CB_POLL_BROADCAST_CANCEL}:")
    )
    app.add_handler(CallbackQueryHandler(poll_handler.callback_notify_no_deck, pattern=f"^{CB_NOTIFY_NO_DECK}:"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_notify_confirm, pattern=f"^{CB_NOTIFY_CONFIRM}:"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_notify_cancel, pattern=f"^{CB_NOTIFY_CANCEL}:"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_poll_org_menu, pattern=f"^{CB_POLL_ORG_MENU}$"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_poll_club, pattern=f"^{CB_POLL_CLUB}:"))
    app.add_handler(CallbackQueryHandler(poll_handler.callback_poll_regulars, pattern=f"^{CB_POLL_REGULARS}:"))
    app.add_handler(
        CallbackQueryHandler(poll_handler.callback_poll_regular_toggle, pattern=f"^{CB_POLL_REGULAR_TOGGLE}:")
    )
    app.add_handler(CallbackQueryHandler(poll_handler.callback_poll_ping, pattern=f"^{CB_POLL_PING}:"))
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
    app.add_handler(CallbackQueryHandler(admin.callback_debug_round_notify, pattern=f"^{CB_DEBUG_ROUND_NOTIFY}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_close_tournament, pattern=f"^{CB_CLOSE_TOURNAMENT}:"))
    app.add_handler(CallbackQueryHandler(admin.callback_reopen_tournament, pattern=f"^{CB_REOPEN_TOURNAMENT}:"))
    app.add_handler(CallbackQueryHandler(schedule_handler.callback_schedule_list, pattern=f"^{CB_SCHEDULE_LIST}$"))
    app.add_handler(CallbackQueryHandler(schedule_handler.callback_schedule_row, pattern=f"^{CB_SCHEDULE_ROW}:"))
    app.add_handler(CallbackQueryHandler(schedule_handler.callback_schedule_toggle, pattern=f"^{CB_SCHEDULE_TOGGLE}:"))
    app.add_handler(
        CallbackQueryHandler(schedule_handler.callback_schedule_edit_field, pattern=f"^{CB_SCHEDULE_EDIT_FIELD}:")
    )
    app.add_handler(
        CallbackQueryHandler(schedule_handler.callback_schedule_imports, pattern=f"^{CB_SCHEDULE_IMPORTS}:")
    )
    app.add_handler(
        CallbackQueryHandler(schedule_handler.callback_schedule_weekday, pattern=f"^{CB_SCHEDULE_WEEKDAY}:")
    )
    app.add_handler(
        CallbackQueryHandler(schedule_handler.callback_schedule_set_weekday, pattern=f"^{CB_SCHEDULE_SET_WEEKDAY}:")
    )
    app.add_handler(CallbackQueryHandler(admin.callback_fill_opponents, pattern=f"^{CB_ADMIN_OPPONENTS}:"))
    app.add_handler(CallbackQueryHandler(app_stats_handler.callback_app_stats_home, pattern=f"^{CB_APP_STATS_HOME}$"))
    app.add_handler(
        CallbackQueryHandler(
            app_stats_handler.callback_app_stats_notify_rounds, pattern=f"^{CB_APP_STATS_NOTIFY_ROUNDS}$"
        )
    )
    app.add_handler(CallbackQueryHandler(features_handler.callback_feature_info, pattern=f"^{CB_FEATURE_INFO}:"))
    app.add_handler(CallbackQueryHandler(features_handler.callback_feature_toggle, pattern=f"^{CB_FEATURE_TOGGLE}:"))
    app.add_handler(CallbackQueryHandler(payment_handler.callback_pay, pattern=f"^{CB_PAY}:"))
    app.add_handler(CallbackQueryHandler(payment_handler.callback_pay_status, pattern=f"^{CB_PAY_STATUS}:"))
    app.add_handler(PollAnswerHandler(poll_handler.handle_poll_answer))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & private, player.message_text_input))

    app.add_error_handler(_error_handler)

    if enable_scheduler:
        setup_scheduler(app)

    return app


def main() -> None:
    app = build_application()

    logger.info("Bot starting (polling)...")
    app.run_polling(allowed_updates=["message", "callback_query", "poll_answer"])


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
