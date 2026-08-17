"""Telegram wrapper for the owner/admin /bingo_preview command."""

from __future__ import annotations

import asyncio
import io
import logging
import secrets

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.base import HandlerResult
from bot.handlers.bingo import MAX_PREVIEW_SEED, BingoPreviewHandler, format_bingo_preview
from core.database import SessionLocal
from services.achievement_bingo_image import render_bingo_board
from services.feature_flags import FeatureFlagService
from services.user import UserService

logger = logging.getLogger(__name__)


def _handler(db) -> BingoPreviewHandler:
    return BingoPreviewHandler(UserService(db), FeatureFlagService(db))


async def cmd_bingo_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply only to the requester with a PNG board and all cell descriptions."""

    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    args = list(context.args or [])
    db = SessionLocal()
    try:
        result = _handler(db).preview(
            user.id,
            args,
            default_seed=secrets.randbelow(MAX_PREVIEW_SEED + 1),
        )
    finally:
        db.close()

    if isinstance(result, HandlerResult):
        await msg.reply_text(result.text)
        return

    png: bytes | None = None
    try:
        png = await asyncio.to_thread(
            render_bingo_board,
            result.draft,
            persona_label=result.persona_label,
        )
    except Exception:  # noqa: BLE001 — текст остаётся полным fallback
        logger.exception("[bingo-preview] board render failed")

    if png is not None:
        try:
            await msg.reply_photo(photo=io.BytesIO(png), caption=result.caption)
        except Exception:  # noqa: BLE001 — описания всё равно отправляем инициатору
            logger.exception("[bingo-preview] could not send board image")

    for text in format_bingo_preview(result):
        await msg.reply_text(text)
