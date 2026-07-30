"""Тонкая обёртка /achievements: разбор аргументов, картинка и текстовый фолбэк."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.achievements import Shelf
from bot.handlers.base import HandlerResult
from bot.telegram.achievements import cmd_achievements
from services.achievements import AchievementView
from services.achievements.definitions import ACHIEVEMENTS


def _update():
    update = MagicMock()
    update.effective_user.id = 111
    update.effective_message.reply_text = AsyncMock()
    update.effective_message.reply_photo = AsyncMock()
    return update


def _context(args=None):
    context = MagicMock()
    context.args = args
    return context


def _shelf():
    return Shelf(
        title="Твои ачивки",
        views=[AchievementView(definition=d, unlocked=False, progress=None) for d in ACHIEVEMENTS.values()],
    )


@pytest.mark.asyncio
@patch("bot.telegram.achievements.SessionLocal")
@patch("bot.telegram.achievements._handler")
async def test_shelf_is_sent_as_picture(handler_factory, session_local):
    handler_factory.return_value.shelf.return_value = _shelf()
    update = _update()

    await cmd_achievements(update, _context())

    handler_factory.return_value.shelf.assert_called_once_with(tg_id=111, query=None)
    update.effective_message.reply_photo.assert_awaited_once()
    session_local.return_value.close.assert_called_once()


@pytest.mark.asyncio
@patch("bot.telegram.achievements.SessionLocal")
@patch("bot.telegram.achievements._handler")
async def test_refusal_goes_as_plain_text(handler_factory, _session_local):
    handler_factory.return_value.shelf.return_value = HandlerResult("Команда пока недоступна.")
    update = _update()

    await cmd_achievements(update, _context())

    update.effective_message.reply_text.assert_awaited_once_with("Команда пока недоступна.")
    update.effective_message.reply_photo.assert_not_awaited()


@pytest.mark.asyncio
@patch("bot.telegram.achievements.SessionLocal")
@patch("bot.telegram.achievements._handler")
async def test_player_name_is_joined_from_args(handler_factory, _session_local):
    handler_factory.return_value.shelf.return_value = HandlerResult("ok")

    await cmd_achievements(_update(), _context(["Иванова", "Алиса"]))

    handler_factory.return_value.shelf.assert_called_once_with(tg_id=111, query="Иванова Алиса")


@pytest.mark.asyncio
@patch("bot.telegram.achievements.render_shelf", side_effect=RuntimeError("шрифт не найден"))
@patch("bot.telegram.achievements.SessionLocal")
@patch("bot.telegram.achievements._handler")
async def test_render_failure_falls_back_to_text(handler_factory, _session_local, _render):
    handler_factory.return_value.shelf.return_value = _shelf()
    update = _update()

    await cmd_achievements(update, _context())

    update.effective_message.reply_photo.assert_not_awaited()
    update.effective_message.reply_text.assert_awaited_once()
