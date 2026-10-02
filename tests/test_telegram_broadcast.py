"""Owner-only рассылка участникам турнира: Telegram-обёртка (`bot/telegram/admin.py`).

Проверяем ровно то, что опасно: кому реально уходит сообщение, что при сбое доставки
отчёт остаётся честным и что черновик нельзя отправить без подтверждения.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import Forbidden

from bot.handlers.base import HandlerResult
from bot.telegram.admin import (
    callback_broadcast_cancel,
    callback_broadcast_confirm,
    callback_broadcast_start,
)
from bot.telegram.player import USER_DATA_PENDING_BROADCAST, message_text_input

OWNER_TG_ID = 111
TOURNAMENT_ID = 42


def _update(data: str, user_id: int = OWNER_TG_ID):
    update = MagicMock()
    update.effective_user.id = user_id
    update.callback_query = AsyncMock()
    update.callback_query.data = data
    return update


def _context(bot: AsyncMock, draft: dict | None = None):
    context = MagicMock()
    context.bot = bot
    context.user_data = {} if draft is None else {USER_DATA_PENDING_BROADCAST: draft}
    return context


def _recipient(tg_id: int, username: str = "player"):
    return SimpleNamespace(tg_id=tg_id, username=username, first_name=username, last_name=None)


def _send_handler(recipients, *, text: str = "Отправляю 1 участникам…"):
    handler = MagicMock()
    handler.handle_broadcast_send.return_value = HandlerResult(text, broadcast_recipients=recipients)
    return handler


@pytest.mark.asyncio
async def test_start_arms_draft_and_shows_prompt():
    update = _update(f"adm_msg:{TOURNAMENT_ID}")
    context = _context(AsyncMock())
    keyboard = MagicMock()
    handler = MagicMock()
    handler.handle_broadcast_start.return_value = HandlerResult("Напишите сообщение", keyboard=keyboard)

    with (
        patch("bot.telegram.admin.SessionLocal"),
        patch("bot.telegram.admin._admin_handler", return_value=handler),
        patch("bot.telegram.admin._log") as log,
    ):
        await callback_broadcast_start(update, context)

    handler.handle_broadcast_start.assert_called_once_with(OWNER_TG_ID, TOURNAMENT_ID)
    assert context.user_data[USER_DATA_PENDING_BROADCAST] == {"tournament_id": TOURNAMENT_ID}
    update.callback_query.edit_message_text.assert_awaited_once_with("Напишите сообщение", reply_markup=keyboard)
    log.assert_called_once_with("broadcast_start", update.effective_user, tournament_id=TOURNAMENT_ID)


@pytest.mark.asyncio
async def test_start_does_not_arm_draft_when_owner_check_fails():
    update = _update(f"adm_msg:{TOURNAMENT_ID}")
    context = _context(AsyncMock())
    handler = MagicMock()
    handler.handle_broadcast_start.return_value = HandlerResult("только владельцу", is_alert=True)

    with (
        patch("bot.telegram.admin.SessionLocal"),
        patch("bot.telegram.admin._admin_handler", return_value=handler),
    ):
        await callback_broadcast_start(update, context)

    assert context.user_data == {}
    update.callback_query.answer.assert_awaited_once_with("только владельцу", show_alert=True)
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_without_draft_does_not_send_anything():
    update = _update(f"adm_msg_go:{TOURNAMENT_ID}")
    bot = AsyncMock()
    context = _context(bot, draft=None)
    handler = _send_handler([_recipient(5)])

    with (
        patch("bot.telegram.admin.SessionLocal"),
        patch("bot.telegram.admin._admin_handler", return_value=handler),
    ):
        await callback_broadcast_confirm(update, context)

    bot.send_message.assert_not_awaited()
    handler.handle_broadcast_send.assert_not_called()
    update.callback_query.answer.assert_awaited_once()
    assert "Черновик" in update.callback_query.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_confirm_refuses_draft_from_another_tournament():
    update = _update(f"adm_msg_go:{TOURNAMENT_ID}")
    bot = AsyncMock()
    context = _context(bot, draft={"tournament_id": TOURNAMENT_ID + 1, "text": "чужое"})
    handler = _send_handler([_recipient(5)])

    with (
        patch("bot.telegram.admin.SessionLocal"),
        patch("bot.telegram.admin._admin_handler", return_value=handler),
    ):
        await callback_broadcast_confirm(update, context)

    bot.send_message.assert_not_awaited()
    handler.handle_broadcast_send.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_sends_to_every_recipient_and_reports():
    update = _update(f"adm_msg_go:{TOURNAMENT_ID}")
    bot = AsyncMock()
    context = _context(bot, draft={"tournament_id": TOURNAMENT_ID, "text": "Всем привет"})
    recipients = [_recipient(5, "alice"), _recipient(6, "bob")]
    handler = _send_handler(recipients)

    with (
        patch("bot.telegram.admin.SessionLocal"),
        patch("bot.telegram.admin._admin_handler", return_value=handler),
        patch("bot.telegram.admin._log"),
    ):
        await callback_broadcast_confirm(update, context)

    assert [call.kwargs["chat_id"] for call in bot.send_message.await_args_list] == [5, 6]
    assert all(call.kwargs["text"] == "Всем привет" for call in bot.send_message.await_args_list)
    final = update.callback_query.edit_message_text.await_args.args[0]
    assert "Отправлено 2 из 2" in final
    assert USER_DATA_PENDING_BROADCAST not in context.user_data
    handler.handle_broadcast_send.assert_called_once_with(OWNER_TG_ID, TOURNAMENT_ID)


@pytest.mark.asyncio
async def test_confirm_counts_blocked_and_failed_recipients():
    update = _update(f"adm_msg_go:{TOURNAMENT_ID}")
    bot = AsyncMock()
    bot.send_message = AsyncMock(side_effect=[None, Forbidden("bot can't initiate conversation"), None])
    context = _context(bot, draft={"tournament_id": TOURNAMENT_ID, "text": "Всем привет"})
    recipients = [_recipient(5), _recipient(6), _recipient(7)]
    handler = _send_handler(recipients)

    with (
        patch("bot.telegram.admin.SessionLocal"),
        patch("bot.telegram.admin._admin_handler", return_value=handler),
        patch("bot.telegram.admin._is_notify_allowed", return_value=True),
        patch("bot.telegram.admin._log"),
    ):
        await callback_broadcast_confirm(update, context)

    final = update.callback_query.edit_message_text.await_args.args[0]
    assert "Отправлено 2 из 3" in final
    assert "id6" in final
    assert "не может писать" in final


@pytest.mark.asyncio
async def test_confirm_skips_recipients_outside_notify_gate():
    update = _update(f"adm_msg_go:{TOURNAMENT_ID}")
    bot = AsyncMock()
    context = _context(bot, draft={"tournament_id": TOURNAMENT_ID, "text": "Всем привет"})
    recipients = [_recipient(5), _recipient(6)]
    handler = _send_handler(recipients)

    with (
        patch("bot.telegram.admin.SessionLocal"),
        patch("bot.telegram.admin._admin_handler", return_value=handler),
        patch("bot.telegram.admin._is_notify_allowed", side_effect=lambda tg_id: tg_id == 5),
        patch("bot.telegram.admin._log"),
    ):
        await callback_broadcast_confirm(update, context)

    assert [call.kwargs["chat_id"] for call in bot.send_message.await_args_list] == [5]
    final = update.callback_query.edit_message_text.await_args.args[0]
    assert "Отправлено 1 из 2" in final
    assert "уведомления выключены" in final


@pytest.mark.asyncio
async def test_confirm_waits_between_batches_to_respect_flood_limit():
    update = _update(f"adm_msg_go:{TOURNAMENT_ID}")
    bot = AsyncMock()
    context = _context(bot, draft={"tournament_id": TOURNAMENT_ID, "text": "Всем привет"})
    recipients = [_recipient(index) for index in range(25)]
    handler = _send_handler(recipients)

    with (
        patch("bot.telegram.admin.SessionLocal"),
        patch("bot.telegram.admin._admin_handler", return_value=handler),
        patch("bot.telegram.admin._is_notify_allowed", return_value=True),
        patch("bot.telegram.admin.asyncio.sleep", new_callable=AsyncMock) as sleep,
        patch("bot.telegram.admin._log"),
    ):
        await callback_broadcast_confirm(update, context)

    assert bot.send_message.await_count == 25
    sleep.assert_awaited_once()  # пауза после 20-го сообщения, не после каждого


@pytest.mark.asyncio
async def test_confirm_drops_draft_and_alerts_when_no_recipients():
    update = _update(f"adm_msg_go:{TOURNAMENT_ID}")
    bot = AsyncMock()
    context = _context(bot, draft={"tournament_id": TOURNAMENT_ID, "text": "Всем привет"})
    handler = MagicMock()
    handler.handle_broadcast_send.return_value = HandlerResult("нет участников", is_alert=True)

    with (
        patch("bot.telegram.admin.SessionLocal"),
        patch("bot.telegram.admin._admin_handler", return_value=handler),
    ):
        await callback_broadcast_confirm(update, context)

    bot.send_message.assert_not_awaited()
    assert context.user_data == {}
    update.callback_query.answer.assert_awaited_once_with("нет участников", show_alert=True)


@pytest.mark.asyncio
async def test_cancel_drops_draft_and_sends_nothing():
    update = _update(f"adm_msg_no:{TOURNAMENT_ID}")
    bot = AsyncMock()
    context = _context(bot, draft={"tournament_id": TOURNAMENT_ID, "text": "Всем привет"})

    with patch("bot.telegram.admin._log"):
        await callback_broadcast_cancel(update, context)

    assert context.user_data == {}
    bot.send_message.assert_not_awaited()
    text = update.callback_query.edit_message_text.await_args.args[0]
    assert "Отменено" in text


@pytest.mark.asyncio
async def test_text_input_turns_message_into_preview_and_stores_draft():
    """Роутер текстового ввода: сообщение владельца → предпросмотр, черновик сохранён."""
    update = MagicMock()
    update.effective_user.id = OWNER_TG_ID
    update.effective_message = AsyncMock()
    update.effective_message.text = "  Всем привет  "
    context = _context(AsyncMock(), draft={"tournament_id": TOURNAMENT_ID})
    keyboard = MagicMock()
    handler = MagicMock()
    handler.handle_broadcast_preview.return_value = HandlerResult("предпросмотр", keyboard=keyboard)

    with (
        patch("bot.telegram.player.SessionLocal"),
        patch("bot.telegram.player._admin_handler", return_value=handler),
        patch("bot.telegram.player._log"),
    ):
        await message_text_input(update, context)

    handler.handle_broadcast_preview.assert_called_once_with(OWNER_TG_ID, TOURNAMENT_ID, "Всем привет")
    assert context.user_data[USER_DATA_PENDING_BROADCAST] == {
        "tournament_id": TOURNAMENT_ID,
        "text": "Всем привет",
    }
    update.effective_message.reply_text.assert_awaited_once_with("предпросмотр", reply_markup=keyboard)


@pytest.mark.asyncio
async def test_text_input_drops_draft_when_owner_check_fails():
    update = MagicMock()
    update.effective_user.id = OWNER_TG_ID
    update.effective_message = AsyncMock()
    update.effective_message.text = "Всем привет"
    context = _context(AsyncMock(), draft={"tournament_id": TOURNAMENT_ID})
    handler = MagicMock()
    handler.handle_broadcast_preview.return_value = HandlerResult("только владельцу", is_alert=True)

    with (
        patch("bot.telegram.player.SessionLocal"),
        patch("bot.telegram.player._admin_handler", return_value=handler),
    ):
        await message_text_input(update, context)

    assert USER_DATA_PENDING_BROADCAST not in context.user_data
    assert context.user_data == {}
