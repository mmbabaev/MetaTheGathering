"""Unit tests for bot/telegram/player.py — Telegram wrappers.

All external dependencies (SessionLocal, handler classes, Telegram objects)
are mocked. Tests verify that the thin wrapper:
  - calls the correct handler method with the right arguments
  - passes result.text / result.keyboard to Telegram
  - manages DB session lifecycle (close() always called)
  - sets user_data state when needed (needs_name, pending_custom, etc.)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.base import HandlerResult
from bot.telegram.player import (
    USER_DATA_PENDING_ADMIN_CUSTOM_ARCH,
    USER_DATA_PENDING_CELLAR_NAME,
    USER_DATA_PENDING_CUSTOM,
    USER_DATA_PENDING_MISSING_CUSTOM_ARCH,
    USER_DATA_PENDING_NAME,
    USER_DATA_PENDING_SETTINGS_NAME,
    callback_archetype,
    callback_archetype_more,
    callback_defer_deck,
    callback_leave_confirm,
    callback_leave_tournament,
    callback_missing_custom_deck,
    callback_pick_missing_deck,
    callback_register,
    callback_set_missing_deck,
    callback_tournament_select,
    cmd_tournaments,
    message_text_input,
)

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_user(tg_id: int = 111):
    u = MagicMock()
    u.id = tg_id
    u.username = "testuser"
    return u


def _make_update(user=None, message_text: str | None = None):
    update = MagicMock()
    update.effective_user = user or _make_user()
    msg = AsyncMock()
    msg.text = message_text
    update.effective_message = msg
    return update


def _make_context(user_data: dict | None = None):
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    # Intentionally no bot_data["impersonation"] — tests fail if code touches it
    ctx.bot_data = {}
    return ctx


def _make_callback_update(data: str, user=None):
    update = MagicMock()
    update.effective_user = user or _make_user()
    query = AsyncMock()
    query.data = data
    update.callback_query = query
    return update


# ── cmd_tournaments ───────────────────────────────────────────────────────────


async def test_cmd_tournaments_replies_with_result():
    result = HandlerResult("Нет активных турниров.")
    update = _make_update()
    ctx = _make_context()

    with patch("bot.telegram.player.SessionLocal") as mock_sl, patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_db = MagicMock()
        mock_sl.return_value = mock_db
        mock_h = MagicMock()
        mock_h.handle_tournaments.return_value = result
        mock_ph.return_value = mock_h

        await cmd_tournaments(update, ctx)

    mock_h.handle_tournaments.assert_called_once_with(tg_id=update.effective_user.id)
    update.effective_message.reply_text.assert_called_once_with("Нет активных турниров.", reply_markup=None)
    mock_db.close.assert_called_once()


async def test_cmd_tournaments_passes_keyboard():
    kb = MagicMock()
    result = HandlerResult("Выберите турнир:", keyboard=kb)
    update = _make_update()

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_tournaments.return_value = result
        await cmd_tournaments(update, _make_context())

    update.effective_message.reply_text.assert_called_once_with("Выберите турнир:", reply_markup=kb)


async def test_cmd_tournaments_no_user():
    update = _make_update()
    update.effective_user = None

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_tournaments.return_value = HandlerResult("ok")
        await cmd_tournaments(update, _make_context())

    mock_ph.return_value.handle_tournaments.assert_called_once_with(tg_id=None)


# ── callback_register ─────────────────────────────────────────────────────────


async def test_callback_register_basic():
    result = HandlerResult("Выберите архетип:")
    update = _make_callback_update("reg:42")
    ctx = _make_context()

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_register.return_value = result
        await callback_register(update, ctx)

    mock_ph.return_value.handle_register.assert_called_once_with(42, tg_id=update.effective_user.id)
    assert USER_DATA_PENDING_NAME not in ctx.user_data


async def test_callback_register_needs_name_sets_user_data():
    result = HandlerResult("Введите имя", needs_name=True)
    update = _make_callback_update("reg:7")
    ctx = _make_context()

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_register.return_value = result
        await callback_register(update, ctx)

    assert ctx.user_data[USER_DATA_PENDING_NAME] == 7


async def test_callback_register_bad_data():
    update = _make_callback_update("reg:notanint")
    with patch("bot.telegram.player.SessionLocal"):
        await callback_register(update, _make_context())
    update.callback_query.answer.assert_called_once_with("Ошибка данных.")


# ── callback_tournament_select ────────────────────────────────────────────────


async def test_callback_tournament_select_edits_message():
    result = HandlerResult("Карточка турнира")
    update = _make_callback_update("t:5")

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_tournament_select.return_value = result
        await callback_tournament_select(update, _make_context())

    mock_ph.return_value.handle_tournament_select.assert_called_once_with(5, tg_id=update.effective_user.id)
    update.callback_query.edit_message_text.assert_called_once()


# ── callback_archetype ────────────────────────────────────────────────────────


async def test_callback_archetype_success():
    result = HandlerResult("Вы записаны как Burn.")
    update = _make_callback_update("arch:3:12")

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_archetype.return_value = result
        await callback_archetype(update, _make_context())

    mock_ph.return_value.handle_archetype.assert_called_once_with(
        update.effective_user.id,
        update.effective_user.username,
        update.effective_user.first_name,
        update.effective_user.last_name,
        3,
        12,
    )
    update.callback_query.edit_message_text.assert_called_once_with("Вы записаны как Burn.")


async def test_callback_archetype_alert():
    result = HandlerResult("Уже записаны.", is_alert=True)
    update = _make_callback_update("arch:3:12")

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_archetype.return_value = result
        await callback_archetype(update, _make_context())

    update.callback_query.answer.assert_called_once_with("Уже записаны.", show_alert=True)
    update.callback_query.edit_message_text.assert_not_called()


async def test_callback_defer_deck_success():
    result = HandlerResult("Вы записаны. Укажите колоду позже.")
    update = _make_callback_update("deck_later:3")

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_defer_deck.return_value = result
        mock_ph.return_value.handle_tournament_select.return_value = HandlerResult("Карточка")
        await callback_defer_deck(update, _make_context())

    mock_ph.return_value.handle_defer_deck.assert_called_once_with(
        update.effective_user.id,
        update.effective_user.username,
        update.effective_user.first_name,
        update.effective_user.last_name,
        3,
    )
    update.callback_query.edit_message_text.assert_called_once_with(result.text)
    update.callback_query.message.reply_text.assert_awaited_once()


async def test_callback_defer_deck_alert():
    result = HandlerResult("Слишком поздно.", is_alert=True)
    update = _make_callback_update("deck_later:3")

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_defer_deck.return_value = result
        await callback_defer_deck(update, _make_context())

    update.callback_query.answer.assert_called_once_with(result.text, show_alert=True)
    update.callback_query.edit_message_text.assert_not_called()


# ── callback_archetype_more ───────────────────────────────────────────────────


async def test_callback_archetype_more():
    result = HandlerResult("Все архетипы", keyboard=MagicMock())
    update = _make_callback_update("arch_more:9")

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_archetype_more.return_value = result
        await callback_archetype_more(update, _make_context())

    mock_ph.return_value.handle_archetype_more.assert_called_once_with(9, tg_id=update.effective_user.id)


# ── callback_leave_tournament ─────────────────────────────────────────────────


async def test_callback_leave_tournament():
    result = HandlerResult("Подтверждение выхода")
    update = _make_callback_update("leave:4")

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_leave_tournament.return_value = result
        await callback_leave_tournament(update, _make_context())

    mock_ph.return_value.handle_leave_tournament.assert_called_once_with(update.effective_user.id, 4)


# ── callback_leave_confirm ────────────────────────────────────────────────────


async def test_callback_leave_confirm():
    result = HandlerResult("Вы вышли.")
    update = _make_callback_update("leave_confirm:4")

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_leave_confirm.return_value = result
        await callback_leave_confirm(update, _make_context())

    mock_ph.return_value.handle_leave_confirm.assert_called_once_with(update.effective_user.id, 4)
    update.callback_query.edit_message_text.assert_called_once_with("Вы вышли.")


# ── message_text_input — pending_name ─────────────────────────────────────────


async def test_message_text_input_pending_name_calls_save():
    result = HandlerResult("Выберите архетип:")
    user = _make_user(222)
    user.username = "alice"
    update = _make_update(user=user, message_text="Иван Петров")
    ctx = _make_context({USER_DATA_PENDING_NAME: 10})

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_save_name_then_register.return_value = result
        await message_text_input(update, ctx)

    mock_ph.return_value.handle_save_name_then_register.assert_called_once_with(222, "alice", "Иван Петров", 10)
    assert USER_DATA_PENDING_NAME not in ctx.user_data


async def test_message_text_input_pending_name_empty_restores_state():
    update = _make_update(message_text="   ")
    ctx = _make_context({USER_DATA_PENDING_NAME: 10})

    with patch("bot.telegram.player.SessionLocal"):
        await message_text_input(update, ctx)

    assert ctx.user_data[USER_DATA_PENDING_NAME] == 10


async def test_message_text_input_invalid_name_keeps_pending_state():
    result = HandlerResult("Нужно указать фамилию и имя.", needs_name=True)
    update = _make_update(message_text="🦉")
    ctx = _make_context({USER_DATA_PENDING_NAME: 10})

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_save_name_then_register.return_value = result
        await message_text_input(update, ctx)

    assert ctx.user_data[USER_DATA_PENDING_NAME] == 10


async def test_message_text_input_cellar_name_reopens_cellar_after_valid_name():
    update = _make_update(message_text="Петров Иван")
    ctx = _make_context({USER_DATA_PENDING_CELLAR_NAME: True})

    with (
        patch("bot.telegram.player.SessionLocal"),
        patch("bot.telegram.player.SettingsHandler") as mock_settings,
        patch("bot.telegram.player.CellarHandler") as mock_cellar,
    ):
        mock_settings.return_value.handle_settings_name_text.return_value = HandlerResult("Имя сохранено")
        mock_cellar.return_value.handle_open.return_value = HandlerResult("Даты", keyboard=MagicMock())
        await message_text_input(update, ctx)

    assert USER_DATA_PENDING_CELLAR_NAME not in ctx.user_data
    mock_cellar.return_value.handle_open.assert_called_once_with(
        tg_id=update.effective_user.id,
        username=update.effective_user.username,
        first_name=None,
        last_name=None,
    )


# ── message_text_input — pending_custom ──────────────────────────────────────


async def test_message_text_input_custom_archetype():
    result = HandlerResult("Записан.")
    update = _make_update(message_text="My Custom Deck")
    ctx = _make_context({USER_DATA_PENDING_CUSTOM: 5})

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_custom_archetype_text.return_value = result
        await message_text_input(update, ctx)

    mock_ph.return_value.handle_custom_archetype_text.assert_called_once_with(
        update.effective_user.id,
        update.effective_user.username,
        update.effective_user.first_name,
        update.effective_user.last_name,
        5,
        "My Custom Deck",
    )


# ── message_text_input — settings name ───────────────────────────────────────


async def test_message_text_input_settings_name():
    result = HandlerResult("Имя сохранено.")
    update = _make_update(message_text="Новое Имя")
    ctx = _make_context({USER_DATA_PENDING_SETTINGS_NAME: True})

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.SettingsHandler") as mock_sh:
        mock_sh.return_value.handle_settings_name_text.return_value = result
        await message_text_input(update, ctx)

    mock_sh.return_value.handle_settings_name_text.assert_called_once_with(update.effective_user.id, "Новое Имя")
    assert USER_DATA_PENDING_SETTINGS_NAME not in ctx.user_data


# ── message_text_input — admin custom archetype ──────────────────────────────


@pytest.mark.asyncio
async def test_message_text_input_admin_custom_arch_sends_keyboard():
    """Keyboard must be passed to reply_text — regression for issue #77."""
    kb = MagicMock()
    result = HandlerResult("✓ Turbo Fog сохранён.", keyboard=kb)
    update = _make_update(message_text="Turbo Fog")
    ctx = _make_context({USER_DATA_PENDING_ADMIN_CUSTOM_ARCH: 7})

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.AdminHandler") as mock_ah:
        mock_ah.return_value.handle_set_participant_custom_arch.return_value = result
        await message_text_input(update, ctx)

    update.effective_message.reply_text.assert_awaited_once()
    _, kwargs = update.effective_message.reply_text.call_args
    assert kwargs.get("reply_markup") is kb


@pytest.mark.asyncio
async def test_message_text_input_admin_custom_arch_calls_handler():
    result = HandlerResult("ok")
    update = _make_update(message_text="Elves")
    ctx = _make_context({USER_DATA_PENDING_ADMIN_CUSTOM_ARCH: 42})

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.AdminHandler") as mock_ah:
        mock_ah.return_value.handle_set_participant_custom_arch.return_value = result
        await message_text_input(update, ctx)

    mock_ah.return_value.handle_set_participant_custom_arch.assert_called_once_with(
        update.effective_user.id, 42, "Elves"
    )
    assert USER_DATA_PENDING_ADMIN_CUSTOM_ARCH not in ctx.user_data


# ── meta-police community flow ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_callback_pick_missing_deck_calls_player_handler():
    keyboard = MagicMock()
    result = HandlerResult("Выберите колоду", keyboard=keyboard)
    update = _make_callback_update("fill_pick:42")

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_pick_missing_deck.return_value = result
        await callback_pick_missing_deck(update, _make_context())

    mock_ph.return_value.handle_pick_missing_deck.assert_called_once_with(update.effective_user.id, 42)
    update.callback_query.edit_message_text.assert_awaited_once_with("Выберите колоду", reply_markup=keyboard)


@pytest.mark.asyncio
async def test_callback_missing_custom_deck_sets_pending_participant():
    update = _make_callback_update("fill_custom:42")
    context = _make_context()

    with patch("bot.telegram.player.SessionLocal"), patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_ph.return_value.handle_pick_missing_deck.return_value = HandlerResult("ok")
        await callback_missing_custom_deck(update, context)

    assert context.user_data[USER_DATA_PENDING_MISSING_CUSTOM_ARCH] == 42
    mock_ph.return_value.handle_pick_missing_deck.assert_called_once_with(update.effective_user.id, 42)


@pytest.mark.asyncio
async def test_callback_set_missing_deck_logs_filler_and_target():
    result = HandlerResult("Сохранено")
    update = _make_callback_update("fill_set:42:7")
    context = _make_context()
    participant = MagicMock(id=42, user_id=5, tournament_id=9)
    target = MagicMock(tg_id=222)

    with (
        patch("bot.telegram.player.SessionLocal") as mock_sl,
        patch("bot.telegram.player.PlayerHandler") as mock_ph,
        patch("bot.telegram.player.TournamentService") as mock_ts,
        patch("bot.telegram.player.UserService") as mock_us,
        patch("bot.telegram.player._log") as mock_log,
        patch("bot.telegram.player.refresh_meta_police_message", new_callable=AsyncMock) as refresh_message,
        patch("bot.telegram.player.announce_completion_if_ready", new_callable=AsyncMock),
    ):
        mock_db = MagicMock()
        mock_sl.return_value = mock_db
        mock_ph.return_value.handle_set_missing_deck.return_value = result
        mock_ts.return_value.get_participant_by_id.return_value = participant
        mock_us.return_value.get_by_id.return_value = target
        await callback_set_missing_deck(update, context)

    mock_ph.return_value.handle_set_missing_deck.assert_called_once_with(update.effective_user.id, 42, 7)
    mock_log.assert_called_once_with(
        "meta_police_deck_recorded",
        update.effective_user,
        tournament_id=9,
        participant_id=42,
        target_tg_id=222,
        archetype_id=7,
    )
    refresh_message.assert_awaited_once_with(context.bot, mock_db, 9)


@pytest.mark.asyncio
async def test_message_text_input_missing_custom_arch_calls_player_handler():
    result = HandlerResult("Сохранено")
    update = _make_update(message_text="Turbo Fog")
    context = _make_context({USER_DATA_PENDING_MISSING_CUSTOM_ARCH: 42})
    participant = MagicMock(id=42, user_id=5, tournament_id=9)

    with (
        patch("bot.telegram.player.SessionLocal") as mock_sl,
        patch("bot.telegram.player.PlayerHandler") as mock_ph,
        patch("bot.telegram.player.TournamentService") as mock_ts,
        patch("bot.telegram.player.UserService") as mock_us,
        patch("bot.telegram.player.refresh_meta_police_message", new_callable=AsyncMock) as refresh_message,
        patch("bot.telegram.player.announce_completion_if_ready", new_callable=AsyncMock),
    ):
        mock_db = MagicMock()
        mock_sl.return_value = mock_db
        mock_ph.return_value.handle_set_missing_custom_deck.return_value = result
        mock_ts.return_value.get_participant_by_id.return_value = participant
        mock_us.return_value.get_by_id.return_value = MagicMock(tg_id=222)
        await message_text_input(update, context)

    mock_ph.return_value.handle_set_missing_custom_deck.assert_called_once_with(
        update.effective_user.id, 42, "Turbo Fog"
    )
    refresh_message.assert_awaited_once_with(context.bot, mock_db, 9)
    assert USER_DATA_PENDING_MISSING_CUSTOM_ARCH not in context.user_data


# ── db session always closed ──────────────────────────────────────────────────


async def test_db_closed_even_on_handler_exception():
    update = _make_update()

    with patch("bot.telegram.player.SessionLocal") as mock_sl, patch("bot.telegram.player.PlayerHandler") as mock_ph:
        mock_db = MagicMock()
        mock_sl.return_value = mock_db
        mock_ph.return_value.handle_tournaments.side_effect = RuntimeError("db exploded")

        with pytest.raises(RuntimeError):
            await cmd_tournaments(update, _make_context())

    mock_db.close.assert_called_once()
