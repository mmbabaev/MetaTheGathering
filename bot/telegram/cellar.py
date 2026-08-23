from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.cellar import CellarHandler
from bot.telegram.common import log_event
from core.database import SessionLocal
from services.feature_flags import FeatureFlagService
from services.user import UserService


async def cmd_cellar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return
    log_event("cmd_cellar", user)
    db = SessionLocal()
    try:
        result = CellarHandler(db, UserService(db), FeatureFlagService(db)).handle_open(
            tg_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
        await message.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
