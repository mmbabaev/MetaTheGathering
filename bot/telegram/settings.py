# Telegram-обёртки для settings-хендлеров

from telegram import Update
from telegram.ext import ContextTypes

from core.database import SessionLocal
from bot.handlers.settings import handle_settings, handle_settings_name_text
from bot.messages import SETTINGS_CHANGE_NAME_PROMPT

USER_DATA_PENDING_SETTINGS_NAME = "pending_settings_name"


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    db = SessionLocal()
    try:
        result = handle_settings(db, user.id)
        await msg.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()


async def callback_settings_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    if context.user_data is None:
        context.user_data = {}
    context.user_data[USER_DATA_PENDING_SETTINGS_NAME] = True
    await query.edit_message_text(SETTINGS_CHANGE_NAME_PROMPT)
    await query.answer()
