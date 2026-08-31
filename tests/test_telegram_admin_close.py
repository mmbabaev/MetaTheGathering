from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.base import HandlerResult
from bot.messages import TOURNAMENT_CLOSED_MSG
from bot.telegram.admin import (
    callback_close_tournament,
    callback_close_tournament_cancel,
    callback_close_tournament_confirm,
)


def _update(data: str, user_id: int = 111):
    update = MagicMock()
    update.effective_user.id = user_id
    update.callback_query = AsyncMock()
    update.callback_query.data = data
    return update


@pytest.mark.asyncio
async def test_close_callback_shows_confirmation_for_nonempty_tournament():
    update = _update("close_t:42")
    context = MagicMock()
    keyboard = MagicMock()
    handler = MagicMock()
    handler.handle_close_tournament_by_id.return_value = HandlerResult("Подтвердите", keyboard=keyboard)

    with (
        patch("bot.telegram.admin.SessionLocal") as session_local,
        patch("bot.telegram.admin._admin_handler", return_value=handler),
        patch("bot.telegram.admin._log") as log,
    ):
        await callback_close_tournament(update, context)

    handler.handle_close_tournament_by_id.assert_called_once_with(111, 42)
    update.callback_query.edit_message_text.assert_awaited_once_with("Подтвердите", reply_markup=keyboard)
    log.assert_called_once_with("close_tournament_prompt", update.effective_user, tournament_id=42)
    session_local.return_value.close.assert_called_once()


@pytest.mark.asyncio
async def test_close_confirm_callback_closes_as_clicking_user():
    update = _update("close_t_yes:42")
    context = MagicMock()
    handler = MagicMock()
    handler.handle_close_tournament_by_id.return_value = HandlerResult(TOURNAMENT_CLOSED_MSG)

    with (
        patch("bot.telegram.admin.SessionLocal") as session_local,
        patch("bot.telegram.admin._admin_handler", return_value=handler),
        patch("bot.telegram.admin._log") as log,
    ):
        await callback_close_tournament_confirm(update, context)

    handler.handle_close_tournament_by_id.assert_called_once_with(111, 42, confirmed=True)
    update.callback_query.edit_message_text.assert_awaited_once_with(TOURNAMENT_CLOSED_MSG)
    log.assert_called_once_with("close_tournament", update.effective_user, tournament_id=42)
    session_local.return_value.close.assert_called_once()


@pytest.mark.asyncio
async def test_close_cancel_callback_returns_tournament_card():
    update = _update("close_t_no:42")
    context = MagicMock()
    keyboard = MagicMock()
    handler = MagicMock()
    handler.handle_tournament_select.return_value = HandlerResult("Карточка", keyboard=keyboard)

    with (
        patch("bot.telegram.admin.SessionLocal") as session_local,
        patch("bot.telegram.admin._player_handler", return_value=handler),
    ):
        await callback_close_tournament_cancel(update, context)

    handler.handle_tournament_select.assert_called_once_with(42, tg_id=111)
    update.callback_query.edit_message_text.assert_awaited_once_with("Карточка", reply_markup=keyboard)
    session_local.return_value.close.assert_called_once()
