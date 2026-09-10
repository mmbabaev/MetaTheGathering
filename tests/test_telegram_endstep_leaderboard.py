from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.base import HandlerResult
from bot.handlers.endstep_leaderboard import EndstepRuLeaderboardLoad
from bot.telegram.endstep_leaderboard import (
    USER_DATA_ENDSTEP_RU_SNAPSHOT,
    callback_endstep_ru_page,
    callback_endstep_ru_refresh,
    cmd_endstep_leaderboard,
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


@pytest.mark.asyncio
async def test_command_loads_and_caches_snapshot():
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=OWNER_ID), effective_message=message)
    context = SimpleNamespace(user_data={})
    snapshot = _snapshot()
    loaded = EndstepRuLeaderboardLoad(HandlerResult("leaderboard", keyboard=MagicMock()), snapshot)

    with patch("bot.telegram.endstep_leaderboard._load", AsyncMock(return_value=loaded)) as load:
        await cmd_endstep_leaderboard(update, context)

    load.assert_awaited_once_with(OWNER_ID)
    assert context.user_data[USER_DATA_ENDSTEP_RU_SNAPSHOT] is snapshot
    message.reply_text.assert_awaited_once_with("leaderboard", reply_markup=loaded.result.keyboard)


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
    query.edit_message_text.assert_awaited_once_with("cached", reply_markup=rendered.keyboard)
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
    query.edit_message_text.assert_awaited_once_with("loaded", reply_markup=loaded.result.keyboard)
    query.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_refresh_acknowledges_immediately_and_replaces_cache(monkeypatch):
    monkeypatch.setattr("bot.telegram.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    calls = []

    async def answer(text=None, **kwargs):
        calls.append(("answer", text, kwargs))

    async def edit_message_text(text, **kwargs):
        calls.append(("edit", text, kwargs))

    query = SimpleNamespace(data="endru_refresh", edit_message_text=edit_message_text, answer=answer)
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=OWNER_ID))
    context = SimpleNamespace(user_data={USER_DATA_ENDSTEP_RU_SNAPSHOT: _snapshot()})
    fresh = _snapshot()
    loaded = EndstepRuLeaderboardLoad(HandlerResult("fresh", keyboard=MagicMock()), fresh)

    with patch("bot.telegram.endstep_leaderboard._load", AsyncMock(return_value=loaded)) as load:
        await callback_endstep_ru_refresh(update, context)

    load.assert_awaited_once_with(OWNER_ID)
    assert calls[0] == ("answer", "Обновляю…", {})
    assert calls[1][0:2] == ("edit", "fresh")
    assert context.user_data[USER_DATA_ENDSTEP_RU_SNAPSHOT] is fresh


@pytest.mark.asyncio
async def test_failed_refresh_discards_stale_cache(monkeypatch):
    monkeypatch.setattr("bot.telegram.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    query = SimpleNamespace(data="endru_refresh", edit_message_text=AsyncMock(), answer=AsyncMock())
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=OWNER_ID))
    context = SimpleNamespace(user_data={USER_DATA_ENDSTEP_RU_SNAPSHOT: _snapshot()})
    loaded = EndstepRuLeaderboardLoad(HandlerResult("temporary error", keyboard=MagicMock()), None)

    with patch("bot.telegram.endstep_leaderboard._load", AsyncMock(return_value=loaded)):
        await callback_endstep_ru_refresh(update, context)

    assert USER_DATA_ENDSTEP_RU_SNAPSHOT not in context.user_data
    query.edit_message_text.assert_awaited_once_with("temporary error", reply_markup=loaded.result.keyboard)


@pytest.mark.asyncio
@pytest.mark.parametrize("callback", [callback_endstep_ru_page, callback_endstep_ru_refresh])
async def test_non_owner_callback_never_loads_or_edits(callback, monkeypatch):
    monkeypatch.setattr("bot.telegram.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    query = SimpleNamespace(data="endru_page:0", edit_message_text=AsyncMock(), answer=AsyncMock())
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=OWNER_ID + 1))
    context = SimpleNamespace(user_data={})

    with patch("bot.telegram.endstep_leaderboard._load", AsyncMock()) as load:
        await callback(update, context)

    load.assert_not_awaited()
    query.edit_message_text.assert_not_awaited()
    query.answer.assert_awaited_once_with("Эта команда доступна только владельцу бота.", show_alert=True)
