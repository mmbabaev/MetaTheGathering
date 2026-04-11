# /start, /help

from telegram import Update
from telegram.ext import ContextTypes


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    await update.effective_message.reply_text(
        "Привет! Используйте /tournaments чтобы увидеть активные турниры и записаться."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    await update.effective_message.reply_text(
        "/tournaments — показать активные турниры и записаться на турнир с выбором архетипа колоды."
    )
