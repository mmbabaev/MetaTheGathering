import logging
from datetime import date

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.cellar import CellarActionResult, CellarHandler
from bot.telegram.common import log_event
from core.database import SessionLocal
from services.cellar import CellarService, cellar_immediate_notification_recipients, format_group_reservation
from services.feature_flags import FeatureFlagService
from services.user import UserService

logger = logging.getLogger(__name__)


def _handler(db) -> CellarHandler:
    return CellarHandler(db, UserService(db), FeatureFlagService(db))


async def _announce(bot, reservation, *, cancelled: bool = False) -> bool:
    """Send only to the explicitly approved per-environment DM recipients."""

    text = format_group_reservation(reservation, cancelled=cancelled)
    delivered = False
    for recipient_tg_id in cellar_immediate_notification_recipients():
        try:
            await bot.send_message(chat_id=recipient_tg_id, text=text)
            delivered = True
        except Exception:  # noqa: BLE001 — one recipient must not break the player's action
            logger.exception("Cellar Telegram notification failed for %s", recipient_tg_id)
    return delivered


async def cmd_cellar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return
    log_event("cmd_cellar", user)
    db = SessionLocal()
    try:
        result = _handler(db).handle_open(
            tg_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
        await message.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()


async def callback_dates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    db = SessionLocal()
    try:
        result = _handler(db).handle_open(
            tg_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
        await _show(query, result)
    finally:
        db.close()


async def callback_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    parsed = await _parse(query, date_index=1, int_indexes=(2,))
    if query is None or user is None or parsed is None:
        return
    event_date, page = parsed
    db = SessionLocal()
    try:
        result = _handler(db).handle_date(tg_id=user.id, event_date=event_date, page=page)
        await _show(query, result)
    finally:
        db.close()


async def callback_deck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    parsed = await _parse(query, date_index=1, int_indexes=(2, 3))
    if query is None or user is None or parsed is None:
        return
    event_date, deck_id, page = parsed
    db = SessionLocal()
    try:
        result = _handler(db).handle_deck(
            tg_id=user.id,
            event_date=event_date,
            deck_id=deck_id,
            page=page,
        )
        await _show(query, result)
    finally:
        db.close()


async def callback_reserve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    parsed = await _parse(query, date_index=1, int_indexes=(2, 3))
    if query is None or user is None or parsed is None:
        return
    event_date, deck_id, page = parsed
    db = SessionLocal()
    try:
        action = _handler(db).handle_reserve(
            tg_id=user.id,
            event_date=event_date,
            deck_id=deck_id,
            page=page,
        )
        await _show_action(query, context, db, action)
    finally:
        db.close()


async def callback_cancel_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    parsed = await _parse(query, int_indexes=(1, 2))
    if query is None or user is None or parsed is None:
        return
    reservation_id, page = parsed
    db = SessionLocal()
    try:
        result = _handler(db).handle_cancel_prompt(tg_id=user.id, reservation_id=reservation_id, page=page)
        await _show(query, result)
    finally:
        db.close()


async def callback_cancel_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    parsed = await _parse(query, int_indexes=(1, 2))
    if query is None or user is None or parsed is None:
        return
    reservation_id, page = parsed
    db = SessionLocal()
    try:
        action = _handler(db).handle_cancel(tg_id=user.id, reservation_id=reservation_id, page=page)
        await _show_action(query, context, db, action)
    finally:
        db.close()


async def callback_noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is not None:
        await update.callback_query.answer()


async def _show(query, result) -> None:
    if result.is_alert:
        await query.answer(result.text, show_alert=True)
        return
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer(result.answer_text)


async def _show_action(query, context, db, action: CellarActionResult) -> None:
    await _show(query, action.result)
    if action.result.is_alert or action.reservation is None:
        return
    delivered = await _announce(context.bot, action.reservation, cancelled=action.cancelled)
    if delivered and not action.cancelled:
        CellarService(db).mark_group_announced(action.reservation.id)


async def _parse(query, *, date_index: int | None = None, int_indexes: tuple[int, ...] = ()):
    if query is None or not query.data:
        return None
    parts = query.data.split(":")
    try:
        values = []
        for index in range(1, len(parts)):
            if index == date_index:
                values.append(date.fromisoformat(parts[index]))
            elif index in int_indexes:
                values.append(int(parts[index]))
        expected = len(int_indexes) + (1 if date_index is not None else 0)
        if len(values) != expected:
            raise ValueError
        return tuple(values)
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.", show_alert=True)
        return None
