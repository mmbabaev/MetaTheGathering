# Точка входа

import asyncio
import logging

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from core.config import settings
from core.database import SessionLocal
from core.schemas import TournamentCreate
from services.tournament import TournamentService
from bot.handlers import common, player, admin
from bot.keyboards import CB_TOURNAMENT, CB_REGISTER, CB_ARCHETYPE, CB_CUSTOM_ARCHETYPE
from bot.scheduler import setup_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


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
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", common.cmd_start))
    app.add_handler(CommandHandler("help", common.cmd_help))
    app.add_handler(CommandHandler("tournaments", player.cmd_tournaments))

    app.add_handler(CommandHandler("add_me", admin.cmd_add_me))
    app.add_handler(CommandHandler("add_player", admin.cmd_add_player))
    app.add_handler(CommandHandler("add_players", admin.cmd_add_players))
    app.add_handler(CommandHandler("tournament_status", admin.cmd_tournament_status))
    app.add_handler(CommandHandler("close_tournament", admin.cmd_close_tournament))

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
        CallbackQueryHandler(player.callback_custom_archetype, pattern=f"^{CB_CUSTOM_ARCHETYPE}:")
    )

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, player.message_custom_archetype)
    )

    setup_scheduler(app)

    if settings.DEBUG:
        _debug_create_tournament()

    logger.info("Bot starting (polling)...")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
