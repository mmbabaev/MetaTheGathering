from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.base import HandlerResult
from bot.telegram.ranked import cmd_ranked_preseason


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
