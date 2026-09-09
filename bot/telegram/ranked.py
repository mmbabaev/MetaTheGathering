"""Telegram wrapper for the admin-only /ranked_preseason command."""

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.ranked import RankedPreseasonHandler
from core.database import SessionLocal
from services.ranked import RankedPreseasonService
from services.user import UserService


def _handler(db) -> RankedPreseasonHandler:
    return RankedPreseasonHandler(RankedPreseasonService(db), UserService(db))


async def cmd_ranked_preseason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    db = SessionLocal()
    try:
        result = _handler(db).handle(user.id)
        await msg.reply_text(result.text)
    finally:
        db.close()
