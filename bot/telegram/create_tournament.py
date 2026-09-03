"""Telegram wrappers for the manual tournament-creation wizard."""

from __future__ import annotations

from datetime import timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.create_tournament import CreateTournamentWizardHandler
from bot.keyboards import Keyboards
from bot.telegram.common import log_event as _log
from bot.tournament_creation import execute_creation_plan
from core import models
from core.database import SessionLocal
from services.tournament_creation import TournamentCreationPlanService
from services.user import UserService

USER_DATA_CREATE_TOURNAMENT = "create_tournament_wizard"


def _handler(db) -> CreateTournamentWizardHandler:
    return CreateTournamentWizardHandler(TournamentCreationPlanService(db), UserService(db), Keyboards())


def _draft(context) -> dict:
    if context.user_data is None:
        context.user_data = {}
    value = context.user_data.setdefault(USER_DATA_CREATE_TOURNAMENT, {})
    if not isinstance(value, dict):
        value = {}
        context.user_data[USER_DATA_CREATE_TOURNAMENT] = value
    return value


def _arg(query, prefix: str) -> str | None:
    data = query.data or ""
    marker = f"{prefix}:"
    return data[len(marker) :] if data.startswith(marker) and len(data) > len(marker) else None


async def cmd_create_tournament_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return
    db = SessionLocal()
    try:
        result = _handler(db).handle_start(user.id)
    finally:
        db.close()
    if result.keyboard is not None:
        _draft(context).clear()
    await message.reply_text(result.text, reply_markup=result.keyboard)


async def _edit(update: Update, context, action) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    db = SessionLocal()
    try:
        result = action(_handler(db), user.id, _draft(context))
    finally:
        db.close()
    if result.is_alert:
        await query.answer(result.text, show_alert=True)
        return
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer()


async def callback_club(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    raw = _arg(query, "ctw_c") if query else None
    if raw is None or not raw.isascii() or not raw.isdigit():
        if query:
            await query.answer("Ошибка данных.", show_alert=True)
        return
    await _edit(update, context, lambda handler, tg_id, draft: handler.handle_club(tg_id, draft, int(raw)))


async def callback_announce_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _edit(update, context, lambda handler, tg_id, draft: handler.handle_announce_now(tg_id, draft))


async def callback_announce_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    raw = _arg(query, "ctw_ad") if query else None
    if raw is None:
        return
    await _edit(update, context, lambda handler, tg_id, draft: handler.handle_announce_date(tg_id, draft, raw))


async def callback_announce_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    raw = _arg(query, "ctw_at") if query else None
    if raw is None:
        return
    await _edit(update, context, lambda handler, tg_id, draft: handler.handle_announce_time(tg_id, draft, raw))


async def callback_event_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    raw = _arg(query, "ctw_ed") if query else None
    if raw is None:
        return
    await _edit(update, context, lambda handler, tg_id, draft: handler.handle_event_date(tg_id, draft, raw))


async def callback_event_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    raw = _arg(query, "ctw_et") if query else None
    if raw is None:
        return
    await _edit(update, context, lambda handler, tg_id, draft: handler.handle_event_time(tg_id, draft, raw))


async def callback_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    target = _arg(query, "ctw_b") if query else None
    if target is None:
        return
    await _edit(update, context, lambda handler, tg_id, draft: handler.handle_back(tg_id, draft, target))


async def callback_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    _draft(context).clear()
    _log("create_tournament_cancel", user)
    await query.edit_message_text("Создание турнира отменено.")
    await query.answer()


async def callback_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    db = SessionLocal()
    try:
        result = _handler(db).handle_confirm(user.id, _draft(context))
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        plan = TournamentCreationPlanService(db).get(result.creation_plan_id)
        execution = None
        if plan is not None and plan.announce_at <= models.utc_now() + timedelta(minutes=1):
            execution = await execute_creation_plan(context.bot, db, plan.id)
        if execution is not None:
            if execution.announced:
                result.text = (
                    f"✅ Турнир создан, объявление отправлено в чат клуба.\nID турнира: {execution.tournament_id}"
                )
            elif execution.tournament_id is not None:
                result.text = f"⚠️ Турнир создан, но объявление не отправилось. Бот повторит автоматически.\nID турнира: {execution.tournament_id}"
            else:
                result.text = f"❌ Не удалось создать турнир: {execution.error}"
        _log("create_tournament_plan", user, creation_plan_id=result.creation_plan_id)
        await query.edit_message_text(result.text)
        await query.answer()
    finally:
        db.close()
