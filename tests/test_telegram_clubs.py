from unittest.mock import AsyncMock, MagicMock, patch

from bot.handlers.base import HandlerResult
from bot.telegram.clubs import callback_chat, cmd_clubs


async def test_cmd_clubs_renders_admin_menu():
    update = MagicMock()
    update.effective_user.id = 42
    update.effective_message = AsyncMock()
    context = MagicMock()
    handler = MagicMock()
    handler.handle_list.return_value = HandlerResult("Клубы", keyboard=MagicMock())

    with (
        patch("bot.telegram.clubs.SessionLocal") as session_local,
        patch("bot.telegram.clubs._handler", return_value=handler),
    ):
        await cmd_clubs(update, context)

    handler.handle_list.assert_called_once_with(42)
    update.effective_message.reply_text.assert_awaited_once()
    session_local.return_value.close.assert_called_once()


async def test_callback_chat_persists_selected_destination():
    update = MagicMock()
    update.effective_user.id = 42
    update.callback_query.data = "club_cfg_chat:4:test"
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.answer = AsyncMock()
    context = MagicMock()
    handler = MagicMock()
    handler.handle_set_destination.return_value = HandlerResult("Сохранено", keyboard=MagicMock())

    with (
        patch("bot.telegram.clubs.SessionLocal") as session_local,
        patch("bot.telegram.clubs._handler", return_value=handler),
        patch("bot.telegram.clubs._log") as log,
    ):
        await callback_chat(update, context)

    handler.handle_set_destination.assert_called_once_with(42, 4, "test")
    update.callback_query.edit_message_text.assert_awaited_once()
    update.callback_query.answer.assert_awaited_once_with("Сохранено")
    log.assert_called_once()
    session_local.return_value.close.assert_called_once()
