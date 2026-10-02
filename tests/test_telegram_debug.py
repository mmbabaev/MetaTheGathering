from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.keyboards import CB_DEBUG_SWISS_CLOSE_CONFIRM
from bot.telegram.debug import (
    callback_debug_fill_tournament,
    callback_debug_meta_police,
    callback_debug_next_round,
    callback_debug_swiss_autoplay,
    callback_debug_swiss_close,
    callback_debug_swiss_close_all_confirm,
    callback_debug_swiss_close_confirm,
    callback_debug_swiss_fill,
    callback_debug_swiss_panel,
    callback_debug_swiss_run_all,
)
from core import models
from core.config import settings
from core.schemas import TournamentCreate
from services.debug_swiss import DebugSwissService
from services.endstep_table_titles import ENDSTEP_RU_CLUB
from services.internal_swiss import InternalSwissService
from services.tournament import TournamentService


def _update(user_id: int = 111, chat_id: int = -222, data: str = "dbg_mpol:42"):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.callback_query = AsyncMock()
    update.callback_query.data = data
    return update


def _context():
    context = MagicMock()
    context.bot = AsyncMock()
    return context


@pytest.mark.asyncio
async def test_debug_meta_police_targets_owner_even_if_button_was_pressed_in_group(monkeypatch):
    monkeypatch.setattr("bot.telegram.debug.settings.DEBUG", True)
    monkeypatch.setattr("bot.telegram.debug.settings.OWNER_CHAT_ID", 111)
    update = _update()
    context = _context()

    with (
        patch("bot.telegram.debug.SessionLocal") as session_local,
        patch(
            "bot.telegram.debug.send_debug_meta_police_preview",
            new_callable=AsyncMock,
            return_value=3,
        ) as preview,
    ):
        await callback_debug_meta_police(update, context)

    preview.assert_awaited_once_with(context.bot, session_local.return_value, 42, requester_tg_id=111)
    update.callback_query.answer.assert_awaited_once_with(
        "Отправил live-превью: 3 игроков без колоды.",
        show_alert=True,
    )
    session_local.return_value.close.assert_called_once()


@pytest.mark.asyncio
async def test_debug_meta_police_rejects_non_owner(monkeypatch):
    monkeypatch.setattr("bot.telegram.debug.settings.DEBUG", True)
    monkeypatch.setattr("bot.telegram.debug.settings.OWNER_CHAT_ID", 999)
    update = _update(user_id=111)

    with patch("bot.telegram.debug.send_debug_meta_police_preview", new_callable=AsyncMock) as preview:
        await callback_debug_meta_police(update, _context())

    preview.assert_not_awaited()
    update.callback_query.answer.assert_awaited_once_with(
        "Кнопка доступна только владельцу в debug-боте.",
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_debug_fill_and_next_round_are_local_db_only(db, user_svc, monkeypatch):
    monkeypatch.setattr("bot.telegram.debug.settings.DEBUG", True)
    admin = user_svc.get_or_create(tg_id=111, first_name="Анна", last_name="Админова")
    admin.is_admin = True
    db.commit()
    admin_tg_id = admin.tg_id
    tournament = TournamentService(db).create_tournament(TournamentCreate(title="Debug", chat_id=5))
    context = _context()

    fill_update = _update(user_id=admin_tg_id, data=f"dbg_fill_t:{tournament.id}")
    with patch("bot.telegram.debug.SessionLocal", return_value=db):
        await callback_debug_fill_tournament(fill_update, context)
    assert db.query(models.Participant).filter_by(tournament_id=tournament.id).count() == 7
    context.bot.send_message.assert_not_awaited()

    round_update = _update(user_id=admin_tg_id, data=f"dbg_next_r:{tournament.id}")
    with patch("bot.telegram.debug.SessionLocal", return_value=db):
        await callback_debug_next_round(round_update, context)
    assert db.query(models.RoundPairing).filter_by(tournament_id=tournament.id, round_number=1).count() == 7
    context.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_debug_fill_offers_real_swiss_round_when_internal_mode_is_enabled(db, user_svc, monkeypatch):
    monkeypatch.setattr("bot.telegram.debug.settings.DEBUG", True)
    admin = user_svc.get_or_create(tg_id=211, first_name="Анна", last_name="Админова")
    admin.is_admin = True
    db.commit()
    tournament = TournamentService(db).create_tournament(
        TournamentCreate(
            title="Internal",
            chat_id=5,
            is_online=True,
            registration_close_at=datetime(2026, 9, 20, 16, 0),
        )
    )
    InternalSwissService(db).set_enabled(tournament.id, admin.tg_id, True)
    update = _update(user_id=admin.tg_id, data=f"dbg_fill_t:{tournament.id}")

    with patch("bot.telegram.debug.SessionLocal", return_value=db):
        await callback_debug_fill_tournament(update, _context())

    button = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.text == "🎲 Создать раунд 1"
    assert button.callback_data == f"sw_next:{tournament.id}"


def _internal_swiss(db, user_svc, monkeypatch, *, tg_id=311, players=8):
    """Debug internal-Swiss tournament in a chat the simulator is allowed to touch."""
    monkeypatch.setattr("bot.telegram.debug.settings.DEBUG", True)
    monkeypatch.setattr("services.debug_swiss.settings.DEBUG", True)
    monkeypatch.setattr("services.debug_swiss.app_cfg.endstep_ru_chat_id", 5)
    monkeypatch.setattr(type(settings), "chat_ids", property(lambda self: [5]))
    admin = user_svc.get_or_create(tg_id=tg_id, first_name="Анна", last_name="Админова")
    admin.is_admin = True
    db.commit()
    tournament = TournamentService(db).create_tournament(
        TournamentCreate(
            title="Internal",
            chat_id=5,
            club=ENDSTEP_RU_CLUB,
            is_online=True,
            engine_mode=models.TournamentEngineMode.INTERNAL_SWISS,
            registration_close_at=models.utc_now(),
            created_by_tg_id=admin.tg_id,
        )
    )
    return admin.tg_id, tournament


@pytest.mark.asyncio
async def test_debug_swiss_fill_and_autoplay_stay_local(db, user_svc, monkeypatch):
    admin_tg_id, tournament = _internal_swiss(db, user_svc, monkeypatch)
    context = _context()

    fill_update = _update(user_id=admin_tg_id, data=f"dbg_sw_f:{tournament.id}:8")
    with patch("bot.telegram.debug.SessionLocal", return_value=db):
        await callback_debug_swiss_fill(fill_update, context)
    assert db.query(models.Participant).filter_by(tournament_id=tournament.id).count() == 8

    step_update = _update(user_id=admin_tg_id, data=f"dbg_sw_a:{tournament.id}")
    with patch("bot.telegram.debug.SessionLocal", return_value=db):
        await callback_debug_swiss_autoplay(step_update, context)
    # The real engine writes canonical RoundMatch rows, not legacy RoundPairing rows.
    assert db.query(models.RoundMatch).filter_by(tournament_id=tournament.id, round_number=1).count() == 4
    context.bot.send_message.assert_not_awaited()

    run_update = _update(user_id=admin_tg_id, data=f"dbg_sw_r:{tournament.id}")
    with patch("bot.telegram.debug.SessionLocal", return_value=db):
        await callback_debug_swiss_run_all(run_update, context)
    assert db.get(models.Tournament, tournament.id).status == models.TournamentStatus.ONGOING
    for update in (fill_update, step_update, run_update):
        assert update.callback_query.answer.await_args.kwargs.get("show_alert") is not True
    context.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_debug_swiss_panel_renders_without_touching_other_chats(db, user_svc, monkeypatch):
    admin_tg_id, tournament = _internal_swiss(db, user_svc, monkeypatch)
    update = _update(user_id=admin_tg_id, data=f"dbg_sw_p:{tournament.id}")
    context = _context()

    with patch("bot.telegram.debug.SessionLocal", return_value=db):
        await callback_debug_swiss_panel(update, context)

    assert "Debug-симулятор Swiss" in update.callback_query.edit_message_text.await_args.args[0]
    context.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_debug_swiss_is_closed_for_non_admins(db, user_svc, monkeypatch):
    admin_tg_id, tournament = _internal_swiss(db, user_svc, monkeypatch)
    user_svc.get_or_create(tg_id=999_999, first_name="Чужой")
    db.commit()
    update = _update(user_id=999_999, data=f"dbg_sw_r:{tournament.id}")

    with patch("bot.telegram.debug.SessionLocal", return_value=db):
        await callback_debug_swiss_run_all(update, _context())

    assert db.get(models.Tournament, tournament.id).status == models.TournamentStatus.REGISTRATION
    update.callback_query.answer.assert_awaited_once_with(
        "Кнопка доступна только администраторам debug-бота.",
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_debug_swiss_is_closed_in_production(db, user_svc, monkeypatch):
    admin_tg_id, tournament = _internal_swiss(db, user_svc, monkeypatch)
    monkeypatch.setattr("bot.telegram.debug.settings.DEBUG", False)
    update = _update(user_id=admin_tg_id, data=f"dbg_sw_r:{tournament.id}")

    with patch("bot.telegram.debug.SessionLocal", return_value=db):
        await callback_debug_swiss_run_all(update, _context())

    assert db.get(models.Tournament, tournament.id).status == models.TournamentStatus.REGISTRATION
    update.callback_query.answer.assert_awaited_once_with(
        "Кнопка доступна только администраторам debug-бота.",
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_debug_swiss_force_close_needs_the_confirmation_button(db, user_svc, monkeypatch):
    admin_tg_id, tournament = _internal_swiss(db, user_svc, monkeypatch)
    DebugSwissService(db).fill_players(tournament.id, 8)
    prompt = _update(user_id=admin_tg_id, data=f"dbg_sw_c:{tournament.id}")

    with patch("bot.telegram.debug.SessionLocal", return_value=db):
        await callback_debug_swiss_close(prompt, _context())
    assert db.get(models.Tournament, tournament.id).status == models.TournamentStatus.REGISTRATION
    assert f"{CB_DEBUG_SWISS_CLOSE_CONFIRM}:{tournament.id}" in {
        button.callback_data
        for row in prompt.callback_query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    }

    confirm = _update(user_id=admin_tg_id, data=f"{CB_DEBUG_SWISS_CLOSE_CONFIRM}:{tournament.id}")
    with patch("bot.telegram.debug.SessionLocal", return_value=db):
        await callback_debug_swiss_close_confirm(confirm, _context())

    assert db.get(models.Tournament, tournament.id).status == models.TournamentStatus.CLOSED
    _context().bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_debug_swiss_close_all_is_admin_only(db, user_svc, monkeypatch):
    admin_tg_id, tournament = _internal_swiss(db, user_svc, monkeypatch)
    user_svc.get_or_create(tg_id=999_999, first_name="Чужой")
    db.commit()
    update = _update(user_id=999_999, data=f"dbg_sw_cca:{tournament.id}")

    with patch("bot.telegram.debug.SessionLocal", return_value=db):
        await callback_debug_swiss_close_all_confirm(update, _context())

    assert db.get(models.Tournament, tournament.id).status == models.TournamentStatus.REGISTRATION
    update.callback_query.answer.assert_awaited_once_with(
        "Кнопка доступна только администраторам debug-бота.",
        show_alert=True,
    )
