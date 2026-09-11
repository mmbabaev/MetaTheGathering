"""Telegram wrappers for the owner-only Endstep RU leaderboard."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.endstep_leaderboard import EndstepRuLeaderboardHandler, EndstepRuLeaderboardLoad
from bot.telegram.common import parse_callback_ints
from core.config import settings
from core.database import SessionLocal
from services.endstep_ru_leaderboard import EndstepRuLeaderboard, EndstepRuLeaderboardService

USER_DATA_ENDSTEP_RU_SNAPSHOT = "endstep_ru_leaderboard_snapshot"


def _load_sync(tg_id: int, page: int = 0) -> EndstepRuLeaderboardLoad:
    db = SessionLocal()
    try:
        handler = EndstepRuLeaderboardHandler(EndstepRuLeaderboardService(db))
        return handler.load(tg_id, page)
    finally:
        db.close()


async def _load(tg_id: int, page: int = 0) -> EndstepRuLeaderboardLoad:
    return await asyncio.to_thread(_load_sync, tg_id, page)


async def callback_endstep_ru_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    if settings.OWNER_CHAT_ID is None or user.id != settings.OWNER_CHAT_ID:
        await query.answer("Эта таблица пока доступна только владельцу бота.", show_alert=True)
        return
    await query.answer()
    loaded = await _load(user.id)
    if loaded.snapshot is not None:
        context.user_data[USER_DATA_ENDSTEP_RU_SNAPSHOT] = loaded.snapshot
    else:
        context.user_data.pop(USER_DATA_ENDSTEP_RU_SNAPSHOT, None)
    await query.edit_message_text(loaded.result.text, reply_markup=loaded.result.keyboard)


async def callback_endstep_ru_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    if settings.OWNER_CHAT_ID is None or user.id != settings.OWNER_CHAT_ID:
        await query.answer("Эта команда доступна только владельцу бота.", show_alert=True)
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return

    snapshot = context.user_data.get(USER_DATA_ENDSTEP_RU_SNAPSHOT)
    if isinstance(snapshot, EndstepRuLeaderboard):
        result = EndstepRuLeaderboardHandler().render(user.id, snapshot, ids[0])
    else:
        loaded = await _load(user.id, ids[0])
        result = loaded.result
        if loaded.snapshot is not None:
            context.user_data[USER_DATA_ENDSTEP_RU_SNAPSHOT] = loaded.snapshot
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer()
