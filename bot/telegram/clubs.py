"""Telegram wrappers for club announcement settings."""

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.clubs import ClubSettingsHandler
from bot.keyboards import Keyboards
from bot.telegram.common import log_event as _log
from core.database import SessionLocal
from services.club_settings import ClubAnnouncementSettingsService
from services.user import UserService


def _handler(db) -> ClubSettingsHandler:
    return ClubSettingsHandler(ClubAnnouncementSettingsService(db), UserService(db), Keyboards())


async def cmd_clubs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return
    db = SessionLocal()
    try:
        result = _handler(db).handle_list(user.id)
    finally:
        db.close()
    await message.reply_text(result.text, reply_markup=result.keyboard)


async def callback_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    db = SessionLocal()
    try:
        result = _handler(db).handle_list(user.id)
    finally:
        db.close()
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer()


async def callback_club(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    try:
        club_index = int((query.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await query.answer("Ошибка данных.", show_alert=True)
        return
    db = SessionLocal()
    try:
        result = _handler(db).handle_club(user.id, club_index)
    finally:
        db.close()
    if result.is_alert:
        await query.answer(result.text, show_alert=True)
        return
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer()


async def callback_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    parts = (query.data or "").split(":")
    if len(parts) != 3 or not parts[1].isascii() or not parts[1].isdigit():
        await query.answer("Ошибка данных.", show_alert=True)
        return
    club_index, destination = int(parts[1]), parts[2]
    db = SessionLocal()
    try:
        result = _handler(db).handle_set_destination(user.id, club_index, destination)
    finally:
        db.close()
    if result.is_alert:
        await query.answer(result.text, show_alert=True)
        return
    _log("club_announcement_destination", user, club_index=club_index, destination=destination)
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer("Сохранено")
