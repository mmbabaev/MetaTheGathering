# Telegram-обёртки для settings-хендлеров

from telegram import Update
from telegram.ext import ContextTypes

from core.database import SessionLocal
from services.user import UserService
from bot.handlers.settings import SettingsHandler
from bot.messages import SETTINGS_CHANGE_NAME_PROMPT


def _settings_handler(db) -> SettingsHandler:
    return SettingsHandler(UserService(db))

USER_DATA_PENDING_SETTINGS_NAME = "pending_settings_name"


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    db = SessionLocal()
    try:
        result = _settings_handler(db).handle_settings(user.id)
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
