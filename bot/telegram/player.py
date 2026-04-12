# Telegram-обёртки для player-хендлеров

from telegram import Update
from telegram.ext import ContextTypes

from core.database import SessionLocal
from bot.handlers.player import (
    handle_tournaments,
    handle_tournament_select,
    handle_register,
    handle_save_name_then_register,
    handle_archetype,
    handle_custom_archetype_text,
)
from bot.handlers.settings import handle_settings_name_text
from bot.keyboards import CB_REGISTER, CB_ARCHETYPE, CB_CUSTOM_ARCHETYPE, CB_TOURNAMENT
from bot.messages import CUSTOM_ARCHETYPE_PROMPT

USER_DATA_PENDING_CUSTOM = "pending_custom_archetype_tournament_id"
USER_DATA_PENDING_NAME = "pending_name_for_tournament_id"
USER_DATA_PENDING_SETTINGS_NAME = "pending_settings_name"


async def cmd_tournaments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    db = SessionLocal()
    try:
        result = handle_tournaments(db)
        await update.effective_message.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()


async def callback_tournament_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    try:
        _, tid_str = query.data.split(":", 1)
        tournament_id = int(tid_str)
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.")
        return
    db = SessionLocal()
    try:
        result = handle_tournament_select(db, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not query.data:
        return
    try:
        _, tid_str = query.data.split(":", 1)
        tournament_id = int(tid_str)
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.")
        return
    db = SessionLocal()
    try:
        result = handle_register(db, tournament_id, tg_id=user.id if user else None)
        if result.needs_name:
            if context.user_data is None:
                context.user_data = {}
            context.user_data[USER_DATA_PENDING_NAME] = tournament_id
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_archetype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not query.data or not user:
        return
    try:
        _, tid_str, aid_str = query.data.split(":", 2)
        tournament_id = int(tid_str)
        archetype_id = int(aid_str)
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.")
        return
    db = SessionLocal()
    try:
        result = handle_archetype(
            db, user.id, user.username, user.first_name, user.last_name,
            tournament_id, archetype_id,
        )
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text)
        await query.answer()
    finally:
        db.close()


async def callback_custom_archetype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    try:
        _, tid_str = query.data.split(":", 1)
        tournament_id = int(tid_str)
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.")
        return
    if context.user_data is None:
        context.user_data = {}
    context.user_data[USER_DATA_PENDING_CUSTOM] = tournament_id
    await query.edit_message_text(CUSTOM_ARCHETYPE_PROMPT)
    await query.answer()


async def message_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Единый обработчик текстовых сообщений для всех состояний user_data."""
    msg = update.effective_message
    user = update.effective_user
    if not msg or not msg.text or not user:
        return
    if context.user_data is None:
        return

    text = msg.text.strip()

    # State: waiting for name to complete registration
    if USER_DATA_PENDING_NAME in context.user_data:
        tournament_id = context.user_data.pop(USER_DATA_PENDING_NAME)
        if not text:
            context.user_data[USER_DATA_PENDING_NAME] = tournament_id
            await msg.reply_text("Введите непустое имя.")
            return
        db = SessionLocal()
        try:
            result = handle_save_name_then_register(
                db, user.id, user.username, text, tournament_id,
            )
            await msg.reply_text(result.text, reply_markup=result.keyboard)
        finally:
            db.close()
        return

    # State: waiting for name change from /settings
    if context.user_data.pop(USER_DATA_PENDING_SETTINGS_NAME, None):
        if not text:
            context.user_data[USER_DATA_PENDING_SETTINGS_NAME] = True
            await msg.reply_text("Введите непустое имя.")
            return
        db = SessionLocal()
        try:
            result = handle_settings_name_text(db, user.id, text)
            await msg.reply_text(result.text)
        finally:
            db.close()
        return

    # State: waiting for custom archetype name
    tournament_id = context.user_data.pop(USER_DATA_PENDING_CUSTOM, None)
    if tournament_id is None:
        return
    if not text:
        context.user_data[USER_DATA_PENDING_CUSTOM] = tournament_id
        await msg.reply_text("Введите непустое название архетипа.")
        return
    db = SessionLocal()
    try:
        result = handle_custom_archetype_text(
            db, user.id, user.username, user.first_name, user.last_name,
            tournament_id, text,
        )
        await msg.reply_text(result.text)
    finally:
        db.close()
