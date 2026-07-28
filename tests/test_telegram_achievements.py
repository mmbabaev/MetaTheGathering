"""Тонкая обёртка /achievements: разбор аргументов и жизненный цикл сессии."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.base import HandlerResult
from bot.telegram.achievements import cmd_achievements


def _update():
    update = MagicMock()
    update.effective_user.id = 111
    update.effective_message.reply_text = AsyncMock()
    return update


def _context(args=None):
    context = MagicMock()
    context.args = args
    return context


@pytest.mark.asyncio
@patch("bot.telegram.achievements.SessionLocal")
@patch("bot.telegram.achievements._handler")
async def test_own_shelf_is_requested_without_query(handler_factory, session_local):
    handler_factory.return_value.handle_achievements.return_value = HandlerResult("🏅 Твои ачивки")
    update = _update()

    await cmd_achievements(update, _context())

    handler_factory.return_value.handle_achievements.assert_called_once_with(tg_id=111, query=None)
    update.effective_message.reply_text.assert_awaited_once_with("🏅 Твои ачивки")
    session_local.return_value.close.assert_called_once()


@pytest.mark.asyncio
@patch("bot.telegram.achievements.SessionLocal")
@patch("bot.telegram.achievements._handler")
async def test_player_name_is_joined_from_args(handler_factory, _session_local):
    handler_factory.return_value.handle_achievements.return_value = HandlerResult("ok")

    await cmd_achievements(_update(), _context(["Иванова", "Алиса"]))

    handler_factory.return_value.handle_achievements.assert_called_once_with(tg_id=111, query="Иванова Алиса")
