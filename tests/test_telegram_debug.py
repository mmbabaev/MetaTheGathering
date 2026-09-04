from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.telegram.debug import (
    callback_debug_fill_tournament,
    callback_debug_meta_police,
    callback_debug_next_round,
)
from core import models
from core.schemas import TournamentCreate
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
    assert db.query(models.Participant).filter_by(tournament_id=tournament.id).count() == 15
    context.bot.send_message.assert_not_awaited()

    round_update = _update(user_id=admin_tg_id, data=f"dbg_next_r:{tournament.id}")
    with patch("bot.telegram.debug.SessionLocal", return_value=db):
        await callback_debug_next_round(round_update, context)
    assert db.query(models.RoundPairing).filter_by(tournament_id=tournament.id, round_number=1).count() == 15
    context.bot.send_message.assert_not_awaited()
