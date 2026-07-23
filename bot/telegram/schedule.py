"""Telegram-обёртки для расписания клубов (issue #124/#125)."""

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.schedule import ScheduleHandler
from bot.keyboards import Keyboards
from bot.telegram.common import log_event as _log
from bot.telegram.common import parse_callback_ints
from core.database import SessionLocal
from services.schedule import ScheduleService
from services.user import UserService


def _schedule_handler(db) -> ScheduleHandler:
    return ScheduleHandler(ScheduleService(db), UserService(db), Keyboards())


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/schedule — расписание + кнопки на каждую строку."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    _log("cmd_schedule", user)
    db = SessionLocal()
    try:
        result = _schedule_handler(db).handle_schedule_list(user.id)
    finally:
        db.close()
    await msg.reply_text(result.text, reply_markup=result.keyboard)


async def callback_schedule_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«⬅️ Назад» из карточки — снова список строк."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    db = SessionLocal()
    try:
        result = _schedule_handler(db).handle_schedule_list(user.id)
    finally:
        db.close()
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer()


async def callback_schedule_row(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Тап по строке расписания — карточка."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (row_id,) = ids
    db = SessionLocal()
    try:
        result = _schedule_handler(db).handle_schedule_row(user.id, row_id)
    finally:
        db.close()
    if result.is_alert:
        await query.answer(result.text, show_alert=True)
        return
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer()


async def callback_schedule_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Тумблер строки — правим БД и СРАЗУ перевешиваем джобы, без перезапуска бота."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (row_id,) = ids
    db = SessionLocal()
    try:
        result = _schedule_handler(db).handle_toggle_row(user.id, row_id)
    finally:
        db.close()
    if result.is_alert:
        await query.answer(result.text, show_alert=True)
        return

    # Ленивый импорт: bot.scheduler импортит bot.telegram — верхнеуровневый импорт замкнул бы цикл.
    from bot.scheduler import reload_schedule_jobs  # noqa: PLC0415

    try:
        reload_schedule_jobs(context.application)
        applied = "Применено сразу."
    except Exception:
        _log("schedule_reload_failed", user, row_id=row_id)
        applied = "⚠️ Сохранено, но перечитать расписание не вышло — применится после рестарта бота."

    _log("schedule_toggle", user, row_id=row_id)
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer(applied)
