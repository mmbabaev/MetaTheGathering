"""Telegram-обёртки для /app_statistics — статистика приложения (только владелец)."""

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.app_stats import AppStatsHandler
from bot.keyboards import Keyboards
from bot.telegram.common import log_event as _log
from bot.telegram.session import db_session
from core.database import SessionLocal
from services.app_stats import AppStatsService


def _stats_handler(db) -> AppStatsHandler:
    return AppStatsHandler(AppStatsService(db), Keyboards())


async def cmd_app_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/app_statistics — меню статистики приложения (только владелец)."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    _log("cmd_app_statistics", user)
    with db_session(SessionLocal) as db:
        result = _stats_handler(db).handle_home(user.id)
    await msg.reply_text(result.text, reply_markup=result.keyboard)


async def callback_app_stats_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«⬅️ Назад» — снова меню статистики."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    with db_session(SessionLocal) as db:
        result = _stats_handler(db).handle_home(user.id)
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer()


async def callback_app_stats_notify_rounds(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Тап по метрике «Уведомления о раундах» — список игроков."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    with db_session(SessionLocal) as db:
        result = _stats_handler(db).handle_notify_rounds_list(user.id)
    if result.is_alert:
        await query.answer(result.text, show_alert=True)
        return
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer()
