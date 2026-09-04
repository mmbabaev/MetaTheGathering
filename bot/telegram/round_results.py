"""Telegram callbacks and targeted delivery for online round results."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.base import HandlerResult
from bot.handlers.round_results import DeliveryResult, RoundResultsHandler
from bot.keyboards import Keyboards
from bot.telegram.common import parse_callback_ints
from core import models
from core.config import settings
from core.database import SessionLocal
from services.aetherhub_import_service import AetherhubImportService

logger = logging.getLogger(__name__)


def _is_notify_allowed(tg_id: int) -> bool:
    allowed = settings.notify_allowed_ids
    return allowed is None or tg_id in allowed


async def _deliver_one(bot, delivery: DeliveryResult) -> None:
    """Deliver only to the genuine opponent/proposer selected by the service."""
    if (
        bot is None
        or delivery.recipient_tg_id is None
        or delivery.recipient_text is None
        or not _is_notify_allowed(delivery.recipient_tg_id)
    ):
        return
    try:
        await bot.send_message(
            chat_id=delivery.recipient_tg_id,
            text=delivery.recipient_text,
            reply_markup=delivery.recipient_keyboard,
        )
    except Exception as exc:  # noqa: BLE001 — result persistence must survive a failed DM
        logger.warning("Could not deliver round result DM to tg_id=%s: %s", delivery.recipient_tg_id, exc)


async def _render(query, result: HandlerResult) -> bool:
    if result.is_alert:
        await query.answer(result.text, show_alert=True)
        return False
    await query.edit_message_text(result.text, reply_markup=result.keyboard, parse_mode=result.parse_mode)
    await query.answer(result.answer_text)
    return True


async def _simple(update: Update, count: int, action) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    values = await parse_callback_ints(query, count)
    if values is None:
        return
    db = SessionLocal()
    try:
        await _render(query, action(RoundResultsHandler(db), user.id, *values))
    finally:
        db.close()


async def callback_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _simple(update, 1, lambda handler, tg_id, tournament_id: handler.handle_open(tournament_id, tg_id))


async def callback_own_wins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _simple(update, 2, lambda handler, tg_id, match_id, wins: handler.handle_own_wins(match_id, tg_id, wins))


async def callback_opponent_wins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _simple(
        update,
        3,
        lambda handler, tg_id, match_id, own, opponent: handler.handle_opponent_wins(match_id, tg_id, own, opponent),
    )


async def callback_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    values = await parse_callback_ints(query, 3)
    if values is None:
        return
    match_id, own, opponent = values
    db = SessionLocal()
    try:
        delivery = RoundResultsHandler(db).handle_send(match_id, user.id, own, opponent)
        if await _render(query, delivery.screen):
            await _deliver_one(context.bot, delivery)
    finally:
        db.close()


async def callback_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _respond(update, context, confirm=True)


async def callback_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _respond(update, context, confirm=False)


async def _respond(update: Update, context: ContextTypes.DEFAULT_TYPE, *, confirm: bool) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    values = await parse_callback_ints(query, 2)
    if values is None:
        return
    match_id, revision = values
    db = SessionLocal()
    try:
        handler = RoundResultsHandler(db)
        delivery = (
            handler.handle_confirm(match_id, revision, user.id)
            if confirm
            else handler.handle_reject(match_id, revision, user.id)
        )
        if await _render(query, delivery.screen):
            await _deliver_one(context.bot, delivery)
    finally:
        db.close()


async def callback_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _simple(
        update,
        2,
        lambda handler, tg_id, tournament_id, round_number: handler.handle_round_status(
            tournament_id, tg_id, round_number or None
        ),
    )


async def callback_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _simple(update, 1, lambda handler, tg_id, tournament_id: handler.handle_admin_list(tournament_id, tg_id))


async def callback_admin_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _simple(update, 1, lambda handler, tg_id, match_id: handler.handle_admin_match(match_id, tg_id))


async def callback_admin_p1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _simple(update, 2, lambda handler, tg_id, match_id, wins: handler.handle_admin_p1(match_id, tg_id, wins))


async def callback_admin_p2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _simple(
        update,
        3,
        lambda handler, tg_id, match_id, left, right: handler.handle_admin_p2(match_id, tg_id, left, right),
    )


async def callback_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _simple(update, 1, lambda handler, tg_id, tournament_id: handler.handle_summary(tournament_id, tg_id))


async def callback_toggle_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        handler = RoundResultsHandler(db)
        result = handler.handle_toggle_view(tournament_id, user.id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.answer(result.answer_text, show_alert=True)
        await query.edit_message_text(
            "Действия с турниром:",
            reply_markup=_admin_more_keyboard(db, tournament_id, user.id),
        )
    finally:
        db.close()


def _admin_more_keyboard(db, tournament_id: int, tg_id: int):
    tournament = db.get(models.Tournament, tournament_id)
    if tournament is None:
        return None
    return Keyboards().admin_more_keyboard(
        tournament_id,
        is_closed=tournament.status == models.TournamentStatus.CLOSED,
        decks_hidden=tournament.decks_hidden,
        show_debug=settings.DEBUG,
        show_debug_meta_police=settings.DEBUG and tg_id == settings.OWNER_CHAT_ID,
        is_online=tournament.is_online,
        has_pairings=AetherhubImportService(db).has_pairings(tournament_id),
        show_round_pairings=tournament.show_round_pairings,
    )
