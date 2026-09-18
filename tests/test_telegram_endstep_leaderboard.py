from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.base import HandlerResult
from bot.handlers.endstep_leaderboard import EndstepRuLeaderboardLoad
from bot.telegram.endstep_leaderboard import (
    USER_DATA_ENDSTEP_RU_SNAPSHOT,
    _load_me_sync,
    _load_sync,
    callback_endstep_ru_me,
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


def test_sync_where_am_i_loads_user_and_cached_leaderboard_services():
    db = MagicMock()
    expected = EndstepRuLeaderboardLoad(HandlerResult("me"), _snapshot())
    with (
        patch("bot.telegram.endstep_leaderboard.SessionLocal", return_value=db),
        patch("bot.telegram.endstep_leaderboard.EndstepRuLeaderboardService") as leaderboard_service,
        patch("bot.telegram.endstep_leaderboard.UserService") as user_service,
        patch("bot.telegram.endstep_leaderboard.EndstepRuLeaderboardHandler") as handler,
    ):
        handler.return_value.load_me.return_value = expected
        loaded = _load_me_sync(OWNER_ID)

    assert loaded is expected
    handler.assert_called_once_with(leaderboard_service.return_value, user_service.return_value)
    handler.return_value.load_me.assert_called_once_with(OWNER_ID)
    db.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_menu_button_loads_and_caches_snapshot_for_any_player():
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
async def test_menu_button_is_public():
    query = SimpleNamespace(edit_message_text=AsyncMock(), answer=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=OWNER_ID + 1), callback_query=query)
    context = SimpleNamespace(user_data={})

    loaded = EndstepRuLeaderboardLoad(HandlerResult("public", keyboard=MagicMock()), _snapshot())
    with patch("bot.telegram.endstep_leaderboard._load", AsyncMock(return_value=loaded)) as load:
        await callback_endstep_ru_open(update, context)

    load.assert_awaited_once_with(OWNER_ID + 1)
    query.edit_message_text.assert_awaited_once()
    query.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_cached_page_does_not_reload_endstep():
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
async def test_page_without_cache_loads_once():
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
async def test_public_page_callback_uses_cache_for_any_player():
    query = SimpleNamespace(data="endru_page:0", edit_message_text=AsyncMock(), answer=AsyncMock())
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=OWNER_ID + 1))
    context = SimpleNamespace(user_data={})

    rendered = HandlerResult("public page", keyboard=MagicMock())
    context.user_data[USER_DATA_ENDSTEP_RU_SNAPSHOT] = _snapshot()
    with (
        patch("bot.telegram.endstep_leaderboard._load", AsyncMock()) as load,
        patch("bot.telegram.endstep_leaderboard.EndstepRuLeaderboardHandler") as handler,
    ):
        handler.return_value.render.return_value = rendered
        await callback_endstep_ru_page(update, context)

    load.assert_not_awaited()
    handler.return_value.render.assert_called_once_with(
        OWNER_ID + 1, context.user_data[USER_DATA_ENDSTEP_RU_SNAPSHOT], 0
    )
    query.edit_message_text.assert_awaited_once()
    query.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_where_am_i_loads_and_caches_snapshot():
    query = SimpleNamespace(edit_message_text=AsyncMock(), answer=AsyncMock())
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=OWNER_ID + 1))
    context = SimpleNamespace(user_data={})
    snapshot = _snapshot()
    loaded = EndstepRuLeaderboardLoad(HandlerResult("highlighted", keyboard=MagicMock()), snapshot)

    with patch("bot.telegram.endstep_leaderboard._load_me", AsyncMock(return_value=loaded)) as load_me:
        await callback_endstep_ru_me(update, context)

    load_me.assert_awaited_once_with(OWNER_ID + 1)
    assert context.user_data[USER_DATA_ENDSTEP_RU_SNAPSHOT] is snapshot
    query.edit_message_text.assert_awaited_once_with(
        "highlighted",
        reply_markup=loaded.result.keyboard,
        parse_mode=None,
    )
    query.answer.assert_awaited_once_with()
