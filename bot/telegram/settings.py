# Telegram-обёртки для settings-хендлеров

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.settings import SettingsHandler
from bot.messages import SETTINGS_CHANGE_ENDSTEP_USERNAME_PROMPT, SETTINGS_CHANGE_NAME_PROMPT
from bot.telegram.common import log_event as _log
from core.database import SessionLocal
from services.user import UserService


def _settings_handler(db) -> SettingsHandler:
    return SettingsHandler(UserService(db))


USER_DATA_PENDING_SETTINGS_NAME = "pending_settings_name"
USER_DATA_PENDING_SETTINGS_ENDSTEP_USERNAME = "pending_settings_endstep_username"


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    _log("cmd_settings", user)
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
    _log("settings_name_start", user)
    if context.user_data is None:
        context.user_data = {}
    context.user_data[USER_DATA_PENDING_SETTINGS_NAME] = True
    await query.edit_message_text(SETTINGS_CHANGE_NAME_PROMPT)
    await query.answer()


async def callback_settings_endstep_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    _log("settings_endstep_username_start", user)
    if context.user_data is None:
        context.user_data = {}
    context.user_data[USER_DATA_PENDING_SETTINGS_ENDSTEP_USERNAME] = True
    await query.edit_message_text(SETTINGS_CHANGE_ENDSTEP_USERNAME_PROMPT)
    await query.answer()


async def callback_toggle_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    _log("settings_toggle_emoji", user)
    db = SessionLocal()
    try:
        result = _settings_handler(db).handle_toggle_emoji(user.id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
    await query.answer()


async def callback_toggle_opponent_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    _log("settings_toggle_opp_notify", user)
    db = SessionLocal()
    try:
        result = _settings_handler(db).handle_toggle_opponent_notify(user.id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
    await query.answer()


async def callback_toggle_achievements_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    _log("settings_toggle_achievements_notify", user)
    db = SessionLocal()
    try:
        result = _settings_handler(db).handle_toggle_achievements_notify(user.id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
    await query.answer()


async def callback_toggle_poll_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    _log("settings_toggle_poll_notify", user)
    db = SessionLocal()
    try:
        result = _settings_handler(db).handle_toggle_poll_notify(user.id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
    await query.answer()


async def callback_toggle_cellar_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    _log("settings_toggle_cellar_notify", user)
    db = SessionLocal()
    try:
        result = _settings_handler(db).handle_toggle_cellar_notify(user.id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
    await query.answer()


async def callback_toggle_status_pairings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    _log("settings_toggle_status_pairings", user)
    db = SessionLocal()
    try:
        result = _settings_handler(db).handle_toggle_status_by_pairings(user.id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
    await query.answer()
