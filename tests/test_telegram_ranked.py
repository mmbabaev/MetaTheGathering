from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.base import HandlerResult
from bot.telegram.ranked import (
    callback_leaderboard_me,
    callback_leaderboard_menu,
    callback_leaderboard_moscow,
    callback_leaderboard_page,
    callback_leaderboard_rules,
    cmd_leaderboard,
    cmd_ranked_preseason,
)


@pytest.mark.asyncio
async def test_leaderboard_command_replies_with_keyboard():
    keyboard = MagicMock()
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_message=message)

    with patch("bot.telegram.ranked.leaderboard_menu", return_value=HandlerResult("menu", keyboard=keyboard)):
        await cmd_leaderboard(update, MagicMock())

    message.reply_text.assert_awaited_once_with("menu", reply_markup=keyboard)


@pytest.mark.asyncio
async def test_leaderboard_menu_callback_edits_message_without_database():
    query = SimpleNamespace(data="rank_menu", edit_message_text=AsyncMock(), answer=AsyncMock())
    update = SimpleNamespace(callback_query=query)
    keyboard = MagicMock()

    with patch("bot.telegram.ranked.leaderboard_menu", return_value=HandlerResult("menu", keyboard=keyboard)):
        await callback_leaderboard_menu(update, MagicMock())

    query.edit_message_text.assert_awaited_once_with("menu", reply_markup=keyboard)
    query.answer.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("callback", "data", "method", "expected_args"),
    [
        (callback_leaderboard_page, "rank_page:2", "handle_page", (2,)),
        (callback_leaderboard_moscow, "rank_moscow", "handle_page", ()),
        (callback_leaderboard_rules, "rank_rules:2", "handle_rules", (2,)),
        (callback_leaderboard_me, "rank_me", "handle_me", (123,)),
    ],
)
async def test_leaderboard_callbacks_edit_requester_message(callback, data, method, expected_args):
    query = SimpleNamespace(data=data, edit_message_text=AsyncMock(), answer=AsyncMock())
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=123))
    keyboard = MagicMock()

    with (
        patch("bot.telegram.ranked.SessionLocal") as session_local,
        patch("bot.telegram.ranked._leaderboard_handler") as handler_factory,
    ):
        db = MagicMock()
        session_local.return_value = db
        getattr(handler_factory.return_value, method).return_value = HandlerResult("screen", keyboard=keyboard)
        await callback(update, MagicMock())

    getattr(handler_factory.return_value, method).assert_called_once_with(*expected_args)
    query.edit_message_text.assert_awaited_once_with("screen", reply_markup=keyboard)
    query.answer.assert_awaited_once_with()
    db.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_ranked_preseason_wrapper_replies_only_to_requester():
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=message)
    context = MagicMock()

    with (
        patch("bot.telegram.ranked.SessionLocal") as session_local,
        patch("bot.telegram.ranked._handler") as handler_factory,
    ):
        db = MagicMock()
        session_local.return_value = db
        handler_factory.return_value.handle.return_value = HandlerResult("top")
        await cmd_ranked_preseason(update, context)

    handler_factory.return_value.handle.assert_called_once_with(123)
    message.reply_text.assert_awaited_once_with("top")
    db.close.assert_called_once_with()
