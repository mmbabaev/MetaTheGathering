from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot.handlers.base import HandlerResult
from bot.telegram.rating import callback_social_rating, cmd_social_rating


async def test_social_rating_command_replies_with_menu_back_button():
    keyboard = MagicMock()
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=message)

    with (
        patch("bot.telegram.rating.SessionLocal") as session_local,
        patch("bot.telegram.rating._handler") as handler,
    ):
        handler.return_value.handle_social_rating.return_value = HandlerResult("social", keyboard=keyboard)
        await cmd_social_rating(update, MagicMock())

    handler.return_value.handle_social_rating.assert_called_once_with(tg_id=123)
    message.reply_text.assert_awaited_once_with("social", reply_markup=keyboard)
    session_local.return_value.close.assert_called_once_with()


async def test_social_rating_menu_button_edits_only_requester_message():
    keyboard = MagicMock()
    query = SimpleNamespace(edit_message_text=AsyncMock(), answer=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=456), callback_query=query)

    with (
        patch("bot.telegram.rating.SessionLocal") as session_local,
        patch("bot.telegram.rating._handler") as handler,
    ):
        handler.return_value.handle_social_rating.return_value = HandlerResult("social", keyboard=keyboard)
        await callback_social_rating(update, MagicMock())

    handler.return_value.handle_social_rating.assert_called_once_with(tg_id=456)
    query.edit_message_text.assert_awaited_once_with("social", reply_markup=keyboard)
    query.answer.assert_awaited_once_with()
    session_local.return_value.close.assert_called_once_with()
