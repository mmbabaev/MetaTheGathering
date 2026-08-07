"""Доставка отчёта об ачивках.

Ключевое: в теневом режиме адресат ровно один — владелец. Игрокам бот про ачивки не
пишет, пока не включён флаг и не сделана фаза 5 (docs/achievements.md §6).
"""

import json
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from bot.telegram.achievements import send_achievements_report
from core import models
from core.config import settings
from core.schemas import TournamentCreate
from services.achievements import AchievementService
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.tournament import TournamentService

OWNER = 424242


@pytest.fixture
def owner_chat(monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", OWNER)
    return OWNER


@pytest.fixture
def played(db, user_svc, archetype_burn):
    user = user_svc.get_or_create(tg_id=8001, first_name="Алиса", last_name="Иванова")
    created = TournamentService(db).create_tournament(TournamentCreate(title="Pauper 1", chat_id=100))
    t = db.get(models.Tournament, created.id)
    t.club = "Goldfish"
    t.started_at = models.utc_now() - timedelta(days=1)
    TournamentService(db).register_participant(
        tournament_id=t.id, user_id=user.id, archetype_id=archetype_burn.id, deck_added_by_tg_id=user.tg_id
    )
    for i in (1, 2):
        db.add(
            models.RoundPairing(
                tournament_id=t.id,
                round_number=i,
                player_name="Иванова Алиса",
                opponent_name=f"Opp{i}",
                player_wins=2,
                opponent_wins=0,
            )
        )
    db.commit()
    FeatureFlagService(db).ensure_defaults()
    return t, user


@pytest.mark.asyncio
async def test_report_goes_only_to_the_owner(db, played, owner_chat):
    tournament, player = played
    bot = AsyncMock()

    sent = await send_achievements_report(bot, db, tournament.id)

    assert sent == 1
    recipients = {call.kwargs["chat_id"] for call in bot.send_message.await_args_list}
    assert recipients == {OWNER}
    assert player.tg_id not in recipients


@pytest.mark.asyncio
async def test_second_run_sends_nothing(db, played, owner_chat):
    tournament, _ = played
    bot = AsyncMock()
    await send_achievements_report(bot, db, tournament.id)
    bot.send_message.reset_mock()

    sent = await send_achievements_report(bot, db, tournament.id)

    assert sent == 0
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_awards_are_marked_notified_after_delivery(db, played, owner_chat):
    tournament, _ = played
    await send_achievements_report(AsyncMock(), db, tournament.id)

    assert AchievementService(db).unnotified_for_tournament(tournament.id) == []


@pytest.mark.asyncio
async def test_disabled_flag_stops_the_engine(db, played, owner_chat):
    tournament, _ = played
    FeatureFlagService(db).toggle(FeatureFlags.ACHIEVEMENTS)
    bot = AsyncMock()

    sent = await send_achievements_report(bot, db, tournament.id)

    assert sent == 0
    bot.send_message.assert_not_awaited()
    assert db.query(models.UserAchievement).count() == 0


@pytest.mark.asyncio
async def test_player_dm_flag_does_not_leak_to_players(db, played, owner_chat):
    """Флаг «слать игрокам» включён, но фаза 5 не сделана — уходит по-прежнему владельцу."""
    tournament, player = played
    FeatureFlagService(db).toggle(FeatureFlags.ACHIEVEMENTS_PLAYER_DM)
    bot = AsyncMock()

    await send_achievements_report(bot, db, tournament.id)

    recipients = {call.kwargs["chat_id"] for call in bot.send_message.await_args_list}
    assert recipients == {OWNER}
    assert player.tg_id not in recipients


@pytest.mark.asyncio
async def test_send_failure_does_not_crash(db, played, owner_chat):
    tournament, _ = played
    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError("telegram is down")

    sent = await send_achievements_report(bot, db, tournament.id)

    assert sent == 0


@pytest.mark.asyncio
async def test_report_is_written_to_separate_structured_log(
    db, played, owner_chat, monkeypatch, tmp_path
):
    tournament, _ = played
    log_dir = tmp_path / "logs" / "achievements"
    monkeypatch.setattr(settings, "ACHIEVEMENT_LOG_DIR", str(log_dir))
    bot = AsyncMock()

    await send_achievements_report(bot, db, tournament.id)

    files = list(log_dir.glob(f"tournament-{tournament.id}-*.json"))
    assert len(files) == 1
    assert list(log_dir.glob("*.tmp")) == []
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["tournament"] == {
        "id": tournament.id,
        "title": tournament.title,
        "club": tournament.club,
    }
    assert payload["messages"] == [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert payload["summary"]["messages"] == len(payload["messages"])
    assert payload["summary"]["granted"] == len(payload["granted"])
    assert payload["summary"]["progress_changes"] == len(payload["progress_changes"])
    assert all("user_id" in item and "code" in item and "evidence" in item for item in payload["granted"])


@pytest.mark.asyncio
async def test_report_is_logged_even_when_owner_chat_is_missing(db, played, monkeypatch, tmp_path):
    tournament, _ = played
    log_dir = tmp_path / "achievement-logs"
    monkeypatch.setattr(settings, "ACHIEVEMENT_LOG_DIR", str(log_dir))
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", None)
    bot = AsyncMock()

    sent = await send_achievements_report(bot, db, tournament.id)

    assert sent == 0
    assert len(list(log_dir.glob(f"tournament-{tournament.id}-*.json"))) == 1
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_log_failure_does_not_block_owner_report(db, played, owner_chat, monkeypatch):
    tournament, _ = played
    monkeypatch.setattr(settings, "ACHIEVEMENT_LOG_DIR", "/not-used")

    def fail(*_args, **_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr("bot.telegram.achievements.write_achievement_report_log", fail)
    bot = AsyncMock()

    sent = await send_achievements_report(bot, db, tournament.id)

    assert sent == 1
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_idempotent_second_run_does_not_create_another_log(
    db, played, owner_chat, monkeypatch, tmp_path
):
    tournament, _ = played
    log_dir = tmp_path / "achievement-logs"
    monkeypatch.setattr(settings, "ACHIEVEMENT_LOG_DIR", str(log_dir))

    await send_achievements_report(AsyncMock(), db, tournament.id)
    await send_achievements_report(AsyncMock(), db, tournament.id)

    assert len(list(log_dir.glob(f"tournament-{tournament.id}-*.json"))) == 1
