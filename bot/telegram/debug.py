"""Safe owner-only actions available in the debug bot."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.handlers.round_results import RoundResultsHandler
from bot.keyboards import CB_DEBUG_NEXT_ROUND, CB_SWISS_NEXT_ROUND
from bot.meta_police_message import send_debug_meta_police_preview
from bot.telegram.common import parse_callback_ints
from core import models
from core.config import settings
from core.database import SessionLocal
from services.debug_tournament import DebugTournamentService
from services.round_results import RoundResultError
from services.user import UserService

logger = logging.getLogger(__name__)


async def callback_debug_meta_police(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send an interactive meta-police preview exclusively to the owner who pressed the button."""
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    if not settings.DEBUG or user.id != settings.OWNER_CHAT_ID:
        await query.answer("Кнопка доступна только владельцу в debug-боте.", show_alert=True)
        return
    try:
        tournament_id = int(query.data.split(":", 1)[1])
    except (AttributeError, IndexError, TypeError, ValueError):
        await query.answer("Ошибка данных.", show_alert=True)
        return

    db = SessionLocal()
    try:
        count = await send_debug_meta_police_preview(
            context.bot,
            db,
            tournament_id,
            requester_tg_id=user.id,
        )
    except ValueError as exc:
        await query.answer(str(exc), show_alert=True)
    except Exception:  # noqa: BLE001 — a debug action must not crash the update loop
        logger.exception("debug meta-police preview failed for #%s", tournament_id)
        await query.answer("Не удалось собрать debug-превью.", show_alert=True)
    else:
        await query.answer(f"Отправил live-превью: {count} игроков без колоды.", show_alert=True)
    finally:
        db.close()


async def callback_debug_fill_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fill only the selected debug tournament with obvious fake local users."""
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    values = await parse_callback_ints(query, 1)
    if values is None:
        return
    (tournament_id,) = values
    db = SessionLocal()
    try:
        if not settings.DEBUG or not UserService(db).is_admin(user.id):
            await query.answer("Кнопка доступна только администраторам debug-бота.", show_alert=True)
            return
        result = DebugTournamentService(db).fill_to_15(tournament_id)
        tournament = db.get(models.Tournament, tournament_id)
        internal = bool(tournament and tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS)
        next_prefix = CB_SWISS_NEXT_ROUND if internal else CB_DEBUG_NEXT_ROUND
        next_label = "🎲 Создать раунд 1" if internal else "🐞 Следующий раунд"
        await query.answer(f"Добавлено: {result.added}. Всего игроков: {result.total}.", show_alert=True)
        await query.edit_message_text(
            "Тестовые игроки готовы. Нажмите «Следующий раунд», чтобы создать первые паринги.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(next_label, callback_data=f"{next_prefix}:{tournament_id}")]]
            ),
        )
    except RoundResultError as exc:
        await query.answer(str(exc), show_alert=True)
    finally:
        db.close()


async def callback_debug_next_round(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Complete the current debug round and create a score-aware random next round."""
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    values = await parse_callback_ints(query, 1)
    if values is None:
        return
    (tournament_id,) = values
    db = SessionLocal()
    try:
        if not settings.DEBUG or not UserService(db).is_admin(user.id):
            await query.answer("Кнопка доступна только администраторам debug-бота.", show_alert=True)
            return
        generated = DebugTournamentService(db).next_round(tournament_id, user.id)
        screen = RoundResultsHandler(db).handle_round_status(tournament_id, user.id, generated.round_number)
        await query.edit_message_text(screen.text, reply_markup=screen.keyboard, parse_mode=screen.parse_mode)
        suffix = (
            f" Предыдущих результатов дополнено: {generated.completed_previous}."
            if generated.completed_previous
            else ""
        )
        await query.answer(f"Создан раунд {generated.round_number}.{suffix}", show_alert=True)
    except RoundResultError as exc:
        await query.answer(str(exc), show_alert=True)
    finally:
        db.close()
