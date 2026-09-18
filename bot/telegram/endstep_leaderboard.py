"""Telegram wrappers for the public Endstep RU leaderboard."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.endstep_leaderboard import EndstepRuLeaderboardHandler, EndstepRuLeaderboardLoad
from bot.telegram.common import parse_callback_ints
from core.database import SessionLocal
from services.endstep_ru_leaderboard import EndstepRuLeaderboard, EndstepRuLeaderboardService
from services.user import UserService

USER_DATA_ENDSTEP_RU_SNAPSHOT = "endstep_ru_leaderboard_snapshot"


def _load_sync(tg_id: int, page: int = 0) -> EndstepRuLeaderboardLoad:
    db = SessionLocal()
    try:
        handler = EndstepRuLeaderboardHandler(EndstepRuLeaderboardService(db))
        return handler.load(tg_id, page)
    finally:
        db.close()


def _load_me_sync(tg_id: int) -> EndstepRuLeaderboardLoad:
    db = SessionLocal()
    try:
        handler = EndstepRuLeaderboardHandler(EndstepRuLeaderboardService(db), UserService(db))
        return handler.load_me(tg_id)
    finally:
        db.close()


async def _load(tg_id: int, page: int = 0) -> EndstepRuLeaderboardLoad:
    return await asyncio.to_thread(_load_sync, tg_id, page)


async def _load_me(tg_id: int) -> EndstepRuLeaderboardLoad:
    return await asyncio.to_thread(_load_me_sync, tg_id)


async def callback_endstep_ru_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    await query.answer()
    loaded = await _load(user.id)
    if loaded.snapshot is not None:
        context.user_data[USER_DATA_ENDSTEP_RU_SNAPSHOT] = loaded.snapshot
    else:
        context.user_data.pop(USER_DATA_ENDSTEP_RU_SNAPSHOT, None)
    await query.edit_message_text(
        loaded.result.text,
        reply_markup=loaded.result.keyboard,
        parse_mode=loaded.result.parse_mode,
    )


async def callback_endstep_ru_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
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
    await query.edit_message_text(result.text, reply_markup=result.keyboard, parse_mode=result.parse_mode)
    await query.answer()


async def callback_endstep_ru_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return

    loaded = await _load_me(user.id)
    if loaded.snapshot is not None:
        context.user_data[USER_DATA_ENDSTEP_RU_SNAPSHOT] = loaded.snapshot
    await query.edit_message_text(
        loaded.result.text,
        reply_markup=loaded.result.keyboard,
        parse_mode=loaded.result.parse_mode,
    )
    await query.answer()
