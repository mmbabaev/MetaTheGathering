"""Thin Telegram wrapper for /bingo_preview."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.base import HandlerResult
from bot.handlers.bingo import BingoPreview, BingoPreviewHandler
from bot.telegram.bingo import cmd_bingo_preview
from services.feature_flags import FeatureFlagService
from services.user import UserService


def _update():
    update = MagicMock()
    update.effective_user.id = 7201
    update.effective_message.reply_photo = AsyncMock()
    update.effective_message.reply_text = AsyncMock()
    return update


def _context(args=None):
    context = MagicMock()
    context.args = args
    return context


def _preview(db) -> BingoPreview:
    user = UserService(db).get_or_create(tg_id=7201, first_name="Админ")
    user.is_admin = True
    db.commit()
    result = BingoPreviewHandler(UserService(db), FeatureFlagService(db)).preview(
        user.tg_id,
        ["regular", "42"],
        default_seed=1,
    )
    assert isinstance(result, BingoPreview)
    return result


@pytest.mark.asyncio
@patch("bot.telegram.bingo.render_bingo_board", return_value=b"png")
@patch("bot.telegram.bingo.secrets.randbelow", return_value=123)
@patch("bot.telegram.bingo.SessionLocal")
@patch("bot.telegram.bingo._handler")
async def test_command_sends_picture_and_text_to_requester(handler_factory, session_local, _random, render, db):
    handler_factory.return_value.preview.return_value = _preview(db)
    update = _update()

    await cmd_bingo_preview(update, _context(["regular", "42"]))

    handler_factory.return_value.preview.assert_called_once_with(7201, ["regular", "42"], default_seed=123)
    update.effective_message.reply_photo.assert_awaited_once()
    assert update.effective_message.reply_text.await_count >= 1
    sent_text = "\n".join(call.args[0] for call in update.effective_message.reply_text.await_args_list)
    assert "Ряд 1" in sent_text
    assert "/bingo_preview regular 42" in sent_text
    render.assert_called_once()
    session_local.return_value.close.assert_called_once()


@pytest.mark.asyncio
@patch("bot.telegram.bingo.SessionLocal")
@patch("bot.telegram.bingo._handler")
async def test_refusal_is_plain_text(handler_factory, session_local):
    handler_factory.return_value.preview.return_value = HandlerResult("нет доступа")
    update = _update()

    await cmd_bingo_preview(update, _context())

    update.effective_message.reply_text.assert_awaited_once_with("нет доступа")
    update.effective_message.reply_photo.assert_not_awaited()
    session_local.return_value.close.assert_called_once()


@pytest.mark.asyncio
@patch("bot.telegram.bingo.render_bingo_board", side_effect=RuntimeError("font"))
@patch("bot.telegram.bingo.SessionLocal")
@patch("bot.telegram.bingo._handler")
async def test_render_failure_still_sends_full_text(handler_factory, _session_local, _render, db):
    handler_factory.return_value.preview.return_value = _preview(db)
    update = _update()

    await cmd_bingo_preview(update, _context(["42"]))

    update.effective_message.reply_photo.assert_not_awaited()
    assert update.effective_message.reply_text.await_count >= 1
