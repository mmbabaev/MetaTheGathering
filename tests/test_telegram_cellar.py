from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest

from bot.handlers.base import HandlerResult
from bot.telegram.cellar import _show


@pytest.mark.asyncio
async def test_repeated_cellar_callback_is_acknowledged_without_error():
    query = AsyncMock()
    query.edit_message_text.side_effect = BadRequest("Message is not modified")
    result = HandlerResult("Колоды из ячейки", answer_text="Уже открыто")

    await _show(query, result)

    query.answer.assert_awaited_once_with("Уже открыто")


@pytest.mark.asyncio
async def test_other_cellar_edit_errors_are_not_suppressed():
    query = AsyncMock()
    query.edit_message_text.side_effect = BadRequest("Message to edit not found")

    with pytest.raises(BadRequest, match="Message to edit not found"):
        await _show(query, HandlerResult("Колоды из ячейки"))

    query.answer.assert_not_awaited()
