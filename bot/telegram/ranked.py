"""Telegram wrappers for public Ranked and the admin preseason report."""

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.leaderboard import RankedLeaderboardHandler
from bot.handlers.ranked import RankedPreseasonHandler
from bot.telegram.common import parse_callback_ints
from core.database import SessionLocal
from services.feature_flags import FeatureFlagService
from services.ranked import RankedPreseasonService
from services.ranked_leaderboard import RankedLeaderboardService
from services.user import UserService


def _handler(db) -> RankedPreseasonHandler:
    return RankedPreseasonHandler(RankedPreseasonService(db), UserService(db))


def _leaderboard_handler(db) -> RankedLeaderboardHandler:
    return RankedLeaderboardHandler(
        RankedLeaderboardService(db),
        UserService(db),
        FeatureFlagService(db),
    )


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg:
        return
    db = SessionLocal()
    try:
        result = _leaderboard_handler(db).handle_page()
        await msg.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()


async def callback_leaderboard_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    db = SessionLocal()
    try:
        result = _leaderboard_handler(db).handle_page(ids[0])
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_leaderboard_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    db = SessionLocal()
    try:
        result = _leaderboard_handler(db).handle_me(user.id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_leaderboard_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    db = SessionLocal()
    try:
        result = _leaderboard_handler(db).handle_rules(ids[0])
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def cmd_ranked_preseason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    db = SessionLocal()
    try:
        result = _handler(db).handle(user.id)
        await msg.reply_text(result.text)
    finally:
        db.close()
