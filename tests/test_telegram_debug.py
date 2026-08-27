from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.telegram.debug import cmd_debug_meta_police


def _update(user_id: int = 111, chat_id: int = 222):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.effective_message = AsyncMock()
    return update


def _context(args):
    context = MagicMock()
    context.args = args
    context.bot = AsyncMock()
    return context


@pytest.mark.asyncio
async def test_debug_meta_police_targets_only_requester(monkeypatch):
    monkeypatch.setattr("bot.telegram.debug.settings.DEBUG", True)
    monkeypatch.setattr("bot.telegram.debug.settings.OWNER_CHAT_ID", 111)
    update = _update()
    context = _context(["42"])

    with (
        patch("bot.telegram.debug.SessionLocal") as session_local,
        patch("bot.telegram.debug.send_debug_meta_police_preview", new_callable=AsyncMock) as preview,
    ):
        await cmd_debug_meta_police(update, context)

    preview.assert_awaited_once_with(context.bot, session_local.return_value, 42, requester_chat_id=222)
    update.effective_message.reply_text.assert_not_awaited()
    session_local.return_value.close.assert_called_once()


@pytest.mark.asyncio
async def test_debug_meta_police_rejects_non_owner(monkeypatch):
    monkeypatch.setattr("bot.telegram.debug.settings.DEBUG", True)
    monkeypatch.setattr("bot.telegram.debug.settings.OWNER_CHAT_ID", 999)
    update = _update(user_id=111)

    with patch("bot.telegram.debug.send_debug_meta_police_preview", new_callable=AsyncMock) as preview:
        await cmd_debug_meta_police(update, _context(["42"]))

    preview.assert_not_awaited()
    update.effective_message.reply_text.assert_awaited_once()
