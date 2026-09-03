"""Unit tests for bot/telegram/settings.py — Telegram wrappers.

All external dependencies (SessionLocal, SettingsHandler, Telegram objects) are
mocked. Tests verify that the thin wrapper:
  - calls the correct handler method with the right arguments
  - passes result.text / result.keyboard to Telegram
  - manages DB session lifecycle (close() always called)
  - sets user_data state when needed (pending settings name)
  - guards against missing user / query
"""

from unittest.mock import AsyncMock, MagicMock, patch

from bot.handlers.base import HandlerResult
from bot.telegram.settings import (
    USER_DATA_PENDING_SETTINGS_ENDSTEP_USERNAME,
    USER_DATA_PENDING_SETTINGS_NAME,
    callback_settings_endstep_username,
    callback_settings_name,
    callback_toggle_cellar_notify,
    callback_toggle_emoji,
    callback_toggle_opponent_notify,
    cmd_settings,
)

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_user(tg_id: int = 111):
    u = MagicMock()
    u.id = tg_id
    u.username = "testuser"
    return u


def _make_cmd_update(user=None):
    update = MagicMock()
    update.effective_user = user or _make_user()
    update.effective_message = AsyncMock()
    return update


def _make_callback_update(user=None):
    update = MagicMock()
    update.effective_user = user or _make_user()
    update.callback_query = AsyncMock()
    return update


def _make_context(user_data: dict | None = None):
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    ctx.bot_data = {}
    return ctx


# ── cmd_settings ──────────────────────────────────────────────────────────────


async def test_cmd_settings_replies_with_text_and_keyboard():
    kb = MagicMock()
    result = HandlerResult("⚙️ Настройки", keyboard=kb)
    update = _make_cmd_update()

    with (
        patch("bot.telegram.settings.SessionLocal") as mock_sl,
        patch("bot.telegram.settings.SettingsHandler") as mock_sh,
    ):
        mock_db = MagicMock()
        mock_sl.return_value = mock_db
        mock_sh.return_value.handle_settings.return_value = result
        await cmd_settings(update, _make_context())

    mock_sh.return_value.handle_settings.assert_called_once_with(update.effective_user.id)
    update.effective_message.reply_text.assert_called_once_with("⚙️ Настройки", reply_markup=kb)
    mock_db.close.assert_called_once()


async def test_cmd_settings_no_user_does_nothing():
    update = _make_cmd_update()
    update.effective_user = None

    with patch("bot.telegram.settings.SessionLocal") as mock_sl:
        await cmd_settings(update, _make_context())

    mock_sl.assert_not_called()
    update.effective_message.reply_text.assert_not_called()


# ── callback_settings_name ────────────────────────────────────────────────────


async def test_callback_settings_name_sets_pending_state():
    update = _make_callback_update()
    ctx = _make_context()

    await callback_settings_name(update, ctx)

    assert ctx.user_data[USER_DATA_PENDING_SETTINGS_NAME] is True
    update.callback_query.edit_message_text.assert_awaited_once()
    update.callback_query.answer.assert_awaited_once()


async def test_callback_settings_name_initializes_user_data_when_none():
    update = _make_callback_update()
    ctx = _make_context(user_data=None)
    ctx.user_data = None

    await callback_settings_name(update, ctx)

    assert ctx.user_data[USER_DATA_PENDING_SETTINGS_NAME] is True


async def test_callback_settings_name_no_query_does_nothing():
    update = _make_callback_update()
    update.callback_query = None
    ctx = _make_context()

    await callback_settings_name(update, ctx)

    assert USER_DATA_PENDING_SETTINGS_NAME not in ctx.user_data


async def test_callback_settings_endstep_username_sets_pending_state():
    update = _make_callback_update()
    ctx = _make_context()

    await callback_settings_endstep_username(update, ctx)

    assert ctx.user_data[USER_DATA_PENDING_SETTINGS_ENDSTEP_USERNAME] is True
    update.callback_query.edit_message_text.assert_awaited_once()
    update.callback_query.answer.assert_awaited_once()


# ── callback_toggle_emoji ─────────────────────────────────────────────────────


async def test_callback_toggle_emoji_edits_message_and_closes_db():
    kb = MagicMock()
    result = HandlerResult("⚙️ Настройки", keyboard=kb)
    update = _make_callback_update()

    with (
        patch("bot.telegram.settings.SessionLocal") as mock_sl,
        patch("bot.telegram.settings.SettingsHandler") as mock_sh,
    ):
        mock_db = MagicMock()
        mock_sl.return_value = mock_db
        mock_sh.return_value.handle_toggle_emoji.return_value = result
        await callback_toggle_emoji(update, _make_context())

    mock_sh.return_value.handle_toggle_emoji.assert_called_once_with(update.effective_user.id)
    update.callback_query.edit_message_text.assert_awaited_once_with("⚙️ Настройки", reply_markup=kb)
    update.callback_query.answer.assert_awaited_once()
    mock_db.close.assert_called_once()


async def test_callback_toggle_emoji_no_user_does_nothing():
    update = _make_callback_update()
    update.effective_user = None

    with patch("bot.telegram.settings.SessionLocal") as mock_sl:
        await callback_toggle_emoji(update, _make_context())

    mock_sl.assert_not_called()


# ── callback_toggle_opponent_notify ───────────────────────────────────────────


async def test_callback_toggle_opponent_notify_edits_message_and_closes_db():
    kb = MagicMock()
    result = HandlerResult("⚙️ Настройки", keyboard=kb)
    update = _make_callback_update()

    with (
        patch("bot.telegram.settings.SessionLocal") as mock_sl,
        patch("bot.telegram.settings.SettingsHandler") as mock_sh,
    ):
        mock_db = MagicMock()
        mock_sl.return_value = mock_db
        mock_sh.return_value.handle_toggle_opponent_notify.return_value = result
        await callback_toggle_opponent_notify(update, _make_context())

    mock_sh.return_value.handle_toggle_opponent_notify.assert_called_once_with(update.effective_user.id)
    update.callback_query.edit_message_text.assert_awaited_once_with("⚙️ Настройки", reply_markup=kb)
    update.callback_query.answer.assert_awaited_once()
    mock_db.close.assert_called_once()


async def test_callback_toggle_opponent_notify_no_query_does_nothing():
    update = _make_callback_update()
    update.callback_query = None

    with patch("bot.telegram.settings.SessionLocal") as mock_sl:
        await callback_toggle_opponent_notify(update, _make_context())

    mock_sl.assert_not_called()


async def test_callback_toggle_cellar_notify_edits_message_and_closes_db():
    kb = MagicMock()
    result = HandlerResult("⚙️ Настройки", keyboard=kb)
    update = _make_callback_update()

    with (
        patch("bot.telegram.settings.SessionLocal") as mock_sl,
        patch("bot.telegram.settings.SettingsHandler") as mock_sh,
    ):
        mock_db = MagicMock()
        mock_sl.return_value = mock_db
        mock_sh.return_value.handle_toggle_cellar_notify.return_value = result
        await callback_toggle_cellar_notify(update, _make_context())

    mock_sh.return_value.handle_toggle_cellar_notify.assert_called_once_with(update.effective_user.id)
    update.callback_query.edit_message_text.assert_awaited_once_with("⚙️ Настройки", reply_markup=kb)
    update.callback_query.answer.assert_awaited_once()
    mock_db.close.assert_called_once()
