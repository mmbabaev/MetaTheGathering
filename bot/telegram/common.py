# Telegram-обёртки для /start и /help

from telegram import Update
from telegram.ext import ContextTypes

from bot.messages import HELP_TEXT


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    await update.effective_message.reply_text(
        "Привет! Используйте /tournaments чтобы увидеть активные турниры и записаться."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    await update.effective_message.reply_text(HELP_TEXT)
