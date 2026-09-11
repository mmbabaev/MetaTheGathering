from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.rating import RatingHandler
from core.database import SessionLocal
from services.tournament import TournamentService
from services.user import UserService


def _handler(db) -> RatingHandler:
    return RatingHandler(TournamentService(db), UserService(db))


async def cmd_social_rating(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    db = SessionLocal()
    try:
        result = _handler(db).handle_social_rating(tg_id=user.id)
        await msg.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()


async def callback_social_rating(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    db = SessionLocal()
    try:
        result = _handler(db).handle_social_rating(tg_id=user.id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()
