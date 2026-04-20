# Telegram-обёртки для /start и /help

from telegram import Update
from telegram.ext import ContextTypes

from core.database import SessionLocal
from core.event_log import event_logger
from services.user import UserService
from bot.messages import HELP_TEXT


def _log(event: str, user, **params) -> None:
    event_logger.log(
        event,
        tg_id=user.id if user else None,
        username=user.username if user else None,
        **params,
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_user:
        return
    user = update.effective_user
    _log("cmd_start", user)
    db = SessionLocal()
    try:
        db_user = UserService(db).get_by_tg_id(user.id)
    finally:
        db.close()

    if db_user and db_user.first_name:
        name_parts = [p for p in [db_user.first_name, db_user.last_name] if p]
        greeting = "Привет, {}! ".format(" ".join(name_parts))
    else:
        greeting = "Привет! "

    await update.effective_message.reply_text(
        greeting + "Используйте /tournaments чтобы увидеть активные турниры и записаться."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    _log("cmd_help", update.effective_user)
    await update.effective_message.reply_text(HELP_TEXT)
