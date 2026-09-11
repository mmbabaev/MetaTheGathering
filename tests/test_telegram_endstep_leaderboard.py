from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.base import HandlerResult
from bot.handlers.endstep_leaderboard import EndstepRuLeaderboardLoad
from bot.telegram.endstep_leaderboard import (
    USER_DATA_ENDSTEP_RU_SNAPSHOT,
    _load_sync,
    callback_endstep_ru_open,
    callback_endstep_ru_page,
)
from services.endstep_ru_leaderboard import EndstepRuLeaderboard

OWNER_ID = 9300


def _snapshot() -> EndstepRuLeaderboard:
    return EndstepRuLeaderboard(
        generated_at=datetime(2026, 9, 10),
        candidate_count=0,
        rows=(),
        missing_usernames=(),
    )


def test_sync_load_reads_database_service_without_constructing_http_client():
    db = MagicMock()
    expected = EndstepRuLeaderboardLoad(HandlerResult("cached"), _snapshot())
    with (
        patch("bot.telegram.endstep_leaderboard.SessionLocal", return_value=db),
        patch("bot.telegram.endstep_leaderboard.EndstepRuLeaderboardService") as service,
        patch("bot.telegram.endstep_leaderboard.EndstepRuLeaderboardHandler") as handler,
    ):
        handler.return_value.load.return_value = expected
        loaded = _load_sync(OWNER_ID)

    assert loaded is expected
    service.assert_called_once_with(db)
    handler.assert_called_once_with(service.return_value)
    db.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_menu_button_loads_and_caches_snapshot(monkeypatch):
    monkeypatch.setattr("bot.telegram.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    query = SimpleNamespace(edit_message_text=AsyncMock(), answer=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=OWNER_ID), callback_query=query)
    context = SimpleNamespace(user_data={})
    snapshot = _snapshot()
    loaded = EndstepRuLeaderboardLoad(HandlerResult("leaderboard", keyboard=MagicMock()), snapshot)

    with patch("bot.telegram.endstep_leaderboard._load", AsyncMock(return_value=loaded)) as load:
        await callback_endstep_ru_open(update, context)

    load.assert_awaited_once_with(OWNER_ID)
    assert context.user_data[USER_DATA_ENDSTEP_RU_SNAPSHOT] is snapshot
    query.answer.assert_awaited_once_with()
    query.edit_message_text.assert_awaited_once_with(
        "leaderboard",
        reply_markup=loaded.result.keyboard,
        parse_mode=None,
    )


@pytest.mark.asyncio
async def test_menu_button_blocks_non_owner(monkeypatch):
    monkeypatch.setattr("bot.telegram.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    query = SimpleNamespace(edit_message_text=AsyncMock(), answer=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=OWNER_ID + 1), callback_query=query)
    context = SimpleNamespace(user_data={})

    with patch("bot.telegram.endstep_leaderboard._load", AsyncMock()) as load:
        await callback_endstep_ru_open(update, context)

    load.assert_not_awaited()
    query.edit_message_text.assert_not_awaited()
    query.answer.assert_awaited_once_with("Эта таблица пока доступна только владельцу бота.", show_alert=True)


@pytest.mark.asyncio
async def test_cached_page_does_not_reload_endstep(monkeypatch):
    monkeypatch.setattr("bot.telegram.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    query = SimpleNamespace(data="endru_page:2", edit_message_text=AsyncMock(), answer=AsyncMock())
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=OWNER_ID))
    snapshot = _snapshot()
    context = SimpleNamespace(user_data={USER_DATA_ENDSTEP_RU_SNAPSHOT: snapshot})
    rendered = HandlerResult("cached", keyboard=MagicMock())

    with (
        patch("bot.telegram.endstep_leaderboard._load", AsyncMock()) as load,
        patch("bot.telegram.endstep_leaderboard.EndstepRuLeaderboardHandler") as handler,
    ):
        handler.return_value.render.return_value = rendered
        await callback_endstep_ru_page(update, context)

    load.assert_not_awaited()
    handler.return_value.render.assert_called_once_with(OWNER_ID, snapshot, 2)
    query.edit_message_text.assert_awaited_once_with("cached", reply_markup=rendered.keyboard, parse_mode=None)
    query.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_page_without_cache_loads_once(monkeypatch):
    monkeypatch.setattr("bot.telegram.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    query = SimpleNamespace(data="endru_page:1", edit_message_text=AsyncMock(), answer=AsyncMock())
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=OWNER_ID))
    context = SimpleNamespace(user_data={})
    snapshot = _snapshot()
    loaded = EndstepRuLeaderboardLoad(HandlerResult("loaded", keyboard=MagicMock()), snapshot)

    with patch("bot.telegram.endstep_leaderboard._load", AsyncMock(return_value=loaded)) as load:
        await callback_endstep_ru_page(update, context)

    load.assert_awaited_once_with(OWNER_ID, 1)
    assert context.user_data[USER_DATA_ENDSTEP_RU_SNAPSHOT] is snapshot
    query.edit_message_text.assert_awaited_once_with(
        "loaded",
        reply_markup=loaded.result.keyboard,
        parse_mode=None,
    )
    query.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_non_owner_page_callback_never_loads_or_edits(monkeypatch):
    monkeypatch.setattr("bot.telegram.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    query = SimpleNamespace(data="endru_page:0", edit_message_text=AsyncMock(), answer=AsyncMock())
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=OWNER_ID + 1))
    context = SimpleNamespace(user_data={})

    with patch("bot.telegram.endstep_leaderboard._load", AsyncMock()) as load:
        await callback_endstep_ru_page(update, context)

    load.assert_not_awaited()
    query.edit_message_text.assert_not_awaited()
    query.answer.assert_awaited_once_with("Эта команда доступна только владельцу бота.", show_alert=True)
