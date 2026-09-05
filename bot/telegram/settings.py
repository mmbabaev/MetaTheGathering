# Telegram-обёртки для settings-хендлеров

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.settings import SettingsHandler
from bot.messages import (
    SETTINGS_CHANGE_ENDSTEP_USERNAME_PROMPT,
    SETTINGS_CHANGE_NAME_PROMPT,
    SETTINGS_CITY_CUSTOM_PROMPT,
)
from bot.telegram.common import log_event as _log
from core.database import SessionLocal
from services.user import UserService


def _settings_handler(db) -> SettingsHandler:
    return SettingsHandler(UserService(db))


USER_DATA_PENDING_SETTINGS_NAME = "pending_settings_name"
USER_DATA_PENDING_SETTINGS_ENDSTEP_USERNAME = "pending_settings_endstep_username"
USER_DATA_PENDING_SETTINGS_CITY = "pending_settings_city"

_SETTINGS_PENDING_KEYS = (
    USER_DATA_PENDING_SETTINGS_NAME,
    USER_DATA_PENDING_SETTINGS_ENDSTEP_USERNAME,
    USER_DATA_PENDING_SETTINGS_CITY,
)


def _set_pending_field(context, key: str | None = None) -> None:
    if context.user_data is None:
        context.user_data = {}
    for pending_key in _SETTINGS_PENDING_KEYS:
        context.user_data.pop(pending_key, None)
    if key is not None:
        context.user_data[key] = True


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
    _set_pending_field(context, USER_DATA_PENDING_SETTINGS_NAME)
    await query.edit_message_text(SETTINGS_CHANGE_NAME_PROMPT)
    await query.answer()


async def callback_settings_endstep_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    _log("settings_endstep_username_start", user)
    _set_pending_field(context, USER_DATA_PENDING_SETTINGS_ENDSTEP_USERNAME)
    await query.edit_message_text(SETTINGS_CHANGE_ENDSTEP_USERNAME_PROMPT)
    await query.answer()


async def callback_settings_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    _log("settings_city_open", user)
    _set_pending_field(context)
    db = SessionLocal()
    try:
        result = _settings_handler(db).handle_city_menu(user.id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
    await query.answer()


async def callback_settings_city_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user or not query.data:
        return
    _log("settings_city_choice", user)
    city_code = query.data.partition(":")[2]
    _set_pending_field(context)
    db = SessionLocal()
    try:
        result = _settings_handler(db).handle_settings_city_choice(user.id, city_code)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer(result.answer_text)
    finally:
        db.close()


async def callback_settings_city_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    _log("settings_city_custom_start", user)
    _set_pending_field(context, USER_DATA_PENDING_SETTINGS_CITY)
    await query.edit_message_text(SETTINGS_CITY_CUSTOM_PROMPT)
    await query.answer()


async def callback_settings_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    _set_pending_field(context)
    db = SessionLocal()
    try:
        result = _settings_handler(db).handle_settings(user.id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
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
