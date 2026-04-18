# Telegram-обёртки для /start и /help

from telegram import Update
from telegram.ext import ContextTypes

from core.database import SessionLocal
from services.user import UserService
from bot.messages import HELP_TEXT


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_user:
        return
    db = SessionLocal()
    try:
        user = UserService(db).get_by_tg_id(update.effective_user.id)
    finally:
        db.close()

    if user and user.first_name:
        name_parts = [p for p in [user.first_name, user.last_name] if p]
        greeting = "Привет, {}! ".format(" ".join(name_parts))
    else:
        greeting = "Привет! "

    await update.effective_message.reply_text(
        greeting + "Используйте /tournaments чтобы увидеть активные турниры и записаться."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    await update.effective_message.reply_text(HELP_TEXT)
