from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot.telegram.admin import callback_export_swiss_players, callback_export_swiss_players_file


async def test_callback_export_swiss_players_edits_explicit_page():
    query = AsyncMock()
    query.data = "export_swiss_players:7:1"
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123, username="admin"), callback_query=query)

    with (
        patch("bot.telegram.admin.SessionLocal") as session_local,
        patch("bot.telegram.admin._admin_handler") as handler,
    ):
        handler.return_value.handle_export_swiss_players_page.return_value = ("Игрок — Очки\nИгрок 50 — 4", 2)

        await callback_export_swiss_players(update, MagicMock())

    handler.return_value.handle_export_swiss_players_page.assert_called_once_with(123, 7, page=1)
    query.edit_message_text.assert_awaited_once()
    assert "Игрок 50" in query.edit_message_text.await_args.args[0]
    assert query.edit_message_text.await_args.kwargs["parse_mode"] == "HTML"
    assert query.edit_message_text.await_args.kwargs["reply_markup"] is not None
    message.reply_text.assert_not_awaited()
    query.answer.assert_awaited_once_with()
    session_local.return_value.close.assert_called_once_with()


async def test_callback_export_swiss_players_file_sends_complete_txt():
    query = AsyncMock()
    query.data = "export_swiss_players_file:7"
    query.message.chat_id = 456
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123, username="admin"), callback_query=query)
    bot = AsyncMock()
    context = SimpleNamespace(bot=bot)

    with (
        patch("bot.telegram.admin.SessionLocal") as session_local,
        patch("bot.telegram.admin._admin_handler") as handler,
    ):
        handler.return_value.handle_export_swiss_players.return_value = "Игрок — Очки — Город\nИгрок 51 — 4 — Москва"

        await callback_export_swiss_players_file(update, context)

    handler.return_value.handle_export_swiss_players.assert_called_once_with(123, 7)
    bot.send_document.assert_awaited_once()
    kwargs = bot.send_document.await_args.kwargs
    assert kwargs["chat_id"] == 456
    assert kwargs["filename"] == "players_points_cities_7.txt"
    assert kwargs["document"].read().decode("utf-8").startswith("Игрок — Очки")
    query.answer.assert_awaited_once_with()
    session_local.return_value.close.assert_called_once_with()
