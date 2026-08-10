"""Доставка отчёта об ачивках.

Ключевое: в теневом режиме адресат ровно один — владелец. Игрокам бот про ачивки не
пишет, пока не включён флаг и не сделана фаза 5 (docs/achievements.md §6).
"""

import json
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import Session

from bot.telegram.achievements import send_achievements_report, send_debug_achievement_notification
from core import models
from core.config import settings
from core.schemas import TournamentCreate
from services.achievement_delivery import (
    RECIPIENT_OWNER,
    RECIPIENT_PLAYER,
    STATUS_CANCELLED,
    create_targeted_player_delivery,
)
from services.achievement_processing_lease import acquire_achievement_lease, release_achievement_lease
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
    t.status = models.TournamentStatus.CLOSED
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
async def test_owner_and_opted_in_player_have_independent_delivery_statuses(db, played, owner_chat, monkeypatch):
    tournament, player = played
    player.notify_achievements = True
    db.commit()
    FeatureFlagService(db).toggle(FeatureFlags.ACHIEVEMENTS_PLAYER_DM)
    monkeypatch.setattr("bot.telegram.achievements._is_notify_allowed", lambda _tg_id: True)
    bot = AsyncMock()

    sent = await send_achievements_report(bot, db, tournament.id)

    assert sent == 2
    assert {call.kwargs["chat_id"] for call in bot.send_message.await_args_list} == {OWNER, player.tg_id}
    rows = db.query(models.AchievementReportDelivery).all()
    assert {(row.recipient_type, row.status) for row in rows} == {
        (RECIPIENT_OWNER, "sent"),
        (RECIPIENT_PLAYER, "sent"),
    }
    assert next(row for row in rows if row.recipient_type == RECIPIENT_PLAYER).user_id == player.id


@pytest.mark.asyncio
async def test_owner_failure_does_not_block_targeted_player_delivery(db, played, owner_chat, monkeypatch):
    tournament, player = played
    player.notify_achievements = True
    db.commit()
    FeatureFlagService(db).toggle(FeatureFlags.ACHIEVEMENTS_PLAYER_DM)
    monkeypatch.setattr("bot.telegram.achievements._is_notify_allowed", lambda _tg_id: True)
    bot = AsyncMock()

    async def send_message(*, chat_id, text):
        if chat_id == OWNER:
            raise RuntimeError("owner unavailable")
        return None

    bot.send_message.side_effect = send_message
    sent = await send_achievements_report(bot, db, tournament.id)

    assert sent == 1
    statuses = {row.recipient_type: row.status for row in db.query(models.AchievementReportDelivery).all()}
    assert statuses == {RECIPIENT_OWNER: "pending", RECIPIENT_PLAYER: "sent"}


@pytest.mark.asyncio
async def test_one_player_failure_does_not_block_another_player(
    db, played, owner_chat, user_svc, archetype_burn, monkeypatch
):
    tournament, first = played
    tournament.status = models.TournamentStatus.REGISTRATION
    second = user_svc.get_or_create(tg_id=8002, first_name="Борис", last_name="Второй")
    TournamentService(db).register_participant(
        tournament_id=tournament.id,
        user_id=second.id,
        archetype_id=archetype_burn.id,
        deck_added_by_tg_id=second.tg_id,
    )
    db.add(
        models.RoundPairing(
            tournament_id=tournament.id,
            round_number=1,
            player_name="Второй Борис",
            opponent_name="Opp",
            player_wins=2,
            opponent_wins=0,
        )
    )
    first.notify_achievements = True
    second.notify_achievements = True
    tournament.status = models.TournamentStatus.CLOSED
    db.commit()
    FeatureFlagService(db).toggle(FeatureFlags.ACHIEVEMENTS_PLAYER_DM)
    monkeypatch.setattr("bot.telegram.achievements._is_notify_allowed", lambda _tg_id: True)
    bot = AsyncMock()

    async def fail_first(*, chat_id, text):
        if chat_id == first.tg_id:
            raise RuntimeError("first player unavailable")
        return None

    bot.send_message.side_effect = fail_first
    sent = await send_achievements_report(bot, db, tournament.id)

    assert sent == 2  # owner + second player
    player_rows = db.query(models.AchievementReportDelivery).filter_by(recipient_type=RECIPIENT_PLAYER).all()
    assert {row.user_id: row.status for row in player_rows} == {first.id: "pending", second.id: "sent"}


@pytest.mark.asyncio
async def test_player_opt_out_cancels_pending_retry(db, played, owner_chat, monkeypatch):
    tournament, player = played
    player.notify_achievements = True
    db.commit()
    FeatureFlagService(db).toggle(FeatureFlags.ACHIEVEMENTS_PLAYER_DM)
    monkeypatch.setattr("bot.telegram.achievements._is_notify_allowed", lambda _tg_id: True)
    first_bot = AsyncMock()

    async def fail_player(*, chat_id, text):
        if chat_id == player.tg_id:
            raise RuntimeError("player unavailable")
        return None

    first_bot.send_message.side_effect = fail_player
    await send_achievements_report(first_bot, db, tournament.id)
    player.notify_achievements = False
    db.commit()

    retry_bot = AsyncMock()
    assert await send_achievements_report(retry_bot, db, tournament.id) == 0
    retry_bot.send_message.assert_not_awaited()
    row = db.query(models.AchievementReportDelivery).filter_by(recipient_type=RECIPIENT_PLAYER).one()
    assert row.status == STATUS_CANCELLED


@pytest.mark.asyncio
async def test_allow_list_blocks_player_queue_even_after_opt_in(db, played, owner_chat, monkeypatch):
    tournament, player = played
    player.notify_achievements = True
    db.commit()
    FeatureFlagService(db).toggle(FeatureFlags.ACHIEVEMENTS_PLAYER_DM)
    monkeypatch.setattr("bot.telegram.achievements._is_notify_allowed", lambda _tg_id: False)

    await send_achievements_report(AsyncMock(), db, tournament.id)

    assert db.query(models.AchievementReportDelivery).filter_by(recipient_type=RECIPIENT_PLAYER).count() == 0


@pytest.mark.asyncio
async def test_debug_delivery_sends_only_requesters_own_payload(db, played, owner_chat, monkeypatch):
    tournament, player = played
    player.notify_achievements = True
    db.commit()
    FeatureFlagService(db).toggle(FeatureFlags.ACHIEVEMENTS_PLAYER_DM)
    monkeypatch.setattr("bot.telegram.achievements._is_notify_allowed", lambda _tg_id: True)
    await send_achievements_report(AsyncMock(), db, tournament.id)
    other = models.User(tg_id=8999, first_name="Чужой")
    db.add(other)
    db.flush()
    db.add(
        models.AchievementReportDelivery(
            report_id="other-report",
            tournament_id=tournament.id,
            recipient_type=RECIPIENT_PLAYER,
            user_id=other.id,
            chat_id=other.tg_id,
            message_index=0,
            payload="OTHER PRIVATE PAYLOAD",
            payload_type="achievement_report",
            payload_version=1,
            status="sent",
        )
    )
    db.commit()
    bot = AsyncMock()

    sent = await send_debug_achievement_notification(bot, db, tournament.id, player.tg_id)

    assert sent >= 1
    assert {call.kwargs["chat_id"] for call in bot.send_message.await_args_list} == {player.tg_id}
    assert all("OTHER PRIVATE PAYLOAD" not in call.kwargs["text"] for call in bot.send_message.await_args_list)


def test_targeted_confirmation_payload_has_one_versioned_recipient(db, played):
    tournament, player = played

    delivery = create_targeted_player_delivery(
        db,
        tournament_id=tournament.id,
        user_id=player.id,
        chat_id=player.tg_id,
        payload_type="peer_confirmation",
        payload_version=2,
        payload="Подтвердите событие",
        idempotency_key="dummy-not-a-real-confirmation-key",
    )
    db.commit()

    repeated = create_targeted_player_delivery(
        db,
        tournament_id=tournament.id,
        user_id=player.id,
        chat_id=player.tg_id,
        payload_type="peer_confirmation",
        payload_version=2,
        payload="Подтвердите событие",
        idempotency_key="dummy-not-a-real-confirmation-key",
    )

    assert delivery.recipient_type == RECIPIENT_PLAYER
    assert repeated.id == delivery.id
    assert delivery.user_id == player.id and delivery.chat_id == player.tg_id
    assert delivery.payload_type == "peer_confirmation" and delivery.payload_version == 2


@pytest.mark.asyncio
async def test_send_failure_does_not_crash(db, played, owner_chat):
    tournament, _ = played
    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError("telegram is down")

    sent = await send_achievements_report(bot, db, tournament.id)

    assert sent == 0
    delivery = db.query(models.AchievementReportDelivery).one()
    assert delivery.status == "pending"
    assert delivery.attempts == 1
    assert delivery.last_error == "RuntimeError"
    assert AchievementService(db).unnotified_for_tournament(tournament.id)


@pytest.mark.asyncio
async def test_failed_report_is_retried_without_reprocessing_achievements(db, played, owner_chat):
    tournament, _ = played
    failed_bot = AsyncMock()
    failed_bot.send_message.side_effect = RuntimeError("telegram is down")
    await send_achievements_report(failed_bot, db, tournament.id)
    achievement_count = db.query(models.UserAchievement).count()

    retry_bot = AsyncMock()
    sent = await send_achievements_report(retry_bot, db, tournament.id)

    assert sent == 1
    retry_bot.send_message.assert_awaited_once()
    delivery = db.query(models.AchievementReportDelivery).one()
    assert delivery.status == "sent"
    assert delivery.attempts == 2
    assert delivery.sent_at is not None
    assert db.query(models.UserAchievement).count() == achievement_count
    assert AchievementService(db).unnotified_for_tournament(tournament.id) == []


@pytest.mark.asyncio
async def test_partial_report_retry_skips_already_delivered_messages(db, played, owner_chat, monkeypatch):
    tournament, _ = played
    monkeypatch.setattr("bot.telegram.achievements.build_report", lambda _result: ["part one", "part two"])
    first_bot = AsyncMock()
    first_bot.send_message.side_effect = [None, RuntimeError("second part failed")]

    first_sent = await send_achievements_report(first_bot, db, tournament.id)

    assert first_sent == 1
    rows = db.query(models.AchievementReportDelivery).order_by(models.AchievementReportDelivery.message_index).all()
    assert [row.status for row in rows] == ["sent", "pending"]
    assert AchievementService(db).unnotified_for_tournament(tournament.id)

    retry_bot = AsyncMock()
    retry_sent = await send_achievements_report(retry_bot, db, tournament.id)

    assert retry_sent == 1
    retry_bot.send_message.assert_awaited_once_with(chat_id=OWNER, text="part two")
    assert [row.status for row in rows] == ["sent", "sent"]
    assert AchievementService(db).unnotified_for_tournament(tournament.id) == []


@pytest.mark.asyncio
async def test_report_created_without_owner_is_delivered_after_configuration(db, played, monkeypatch):
    tournament, _ = played
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", None)
    bot = AsyncMock()

    assert await send_achievements_report(bot, db, tournament.id) == 0
    delivery = db.query(models.AchievementReportDelivery).one()
    assert delivery.chat_id is None and delivery.status == "pending"

    monkeypatch.setattr(settings, "OWNER_CHAT_ID", OWNER)
    assert await send_achievements_report(bot, db, tournament.id) == 1
    bot.send_message.assert_awaited_once_with(chat_id=OWNER, text=delivery.payload)
    assert delivery.chat_id == OWNER and delivery.status == "sent"


@pytest.mark.asyncio
async def test_report_is_written_to_separate_structured_log(db, played, owner_chat, monkeypatch, tmp_path):
    tournament, _ = played
    log_dir = tmp_path / "logs" / "achievements"
    monkeypatch.setattr(settings, "ACHIEVEMENT_LOG_DIR", str(log_dir))
    bot = AsyncMock()

    await send_achievements_report(bot, db, tournament.id)

    files = list(log_dir.glob(f"tournament-{tournament.id}-*.json"))
    assert len(files) == 1
    assert list(log_dir.glob("*.tmp")) == []
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["tournament"] == {
        "id": tournament.id,
        "title": tournament.title,
        "club": tournament.club,
    }
    assert payload["messages"] == [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert payload["summary"]["messages"] == len(payload["messages"])
    assert payload["summary"]["granted"] == len(payload["granted"])
    assert payload["summary"]["progress_changes"] == len(payload["progress_changes"])
    assert payload["summary"]["status"] == "completed"
    assert payload["summary"]["processing_run_id"] is not None
    assert all("user_id" in item and "code" in item and "evidence" in item for item in payload["granted"])


@pytest.mark.asyncio
async def test_rule_failure_is_visible_to_owner_and_persisted_safely(db, played, owner_chat, monkeypatch):
    tournament, _ = played
    private_message = "private-data-must-not-be-stored"

    def fail(_self, _ctx):
        raise RuntimeError(private_message)

    monkeypatch.setattr("services.achievements.rules.DebutRule.evaluate", fail)
    bot = AsyncMock()

    sent = await send_achievements_report(bot, db, tournament.id)

    assert sent == 1
    text = bot.send_message.await_args.kwargs["text"]
    assert "⚠️ ОШИБКИ РАСЧЁТА" in text
    assert "debut — RuntimeError" in text
    assert private_message not in text
    run = db.query(models.AchievementProcessingRun).one()
    assert run.status == "partial"
    assert run.rules_total == 7 and run.rules_failed == 1
    assert json.loads(run.rule_errors_json) == [{"code": "debut", "error_type": "RuntimeError"}]
    assert private_message not in run.rule_errors_json


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
async def test_idempotent_second_run_does_not_create_another_log(db, played, owner_chat, monkeypatch, tmp_path):
    tournament, _ = played
    log_dir = tmp_path / "achievement-logs"
    monkeypatch.setattr(settings, "ACHIEVEMENT_LOG_DIR", str(log_dir))

    await send_achievements_report(AsyncMock(), db, tournament.id)
    await send_achievements_report(AsyncMock(), db, tournament.id)

    assert len(list(log_dir.glob(f"tournament-{tournament.id}-*.json"))) == 1


@pytest.mark.asyncio
async def test_live_lease_prevents_duplicate_processing_and_delivery(db, played, owner_chat):
    tournament, _ = played
    blocker = Session(db.bind)
    token = acquire_achievement_lease(blocker, tournament.id)
    assert token is not None
    bot = AsyncMock()
    try:
        assert await send_achievements_report(bot, db, tournament.id) == 0
        bot.send_message.assert_not_awaited()
        assert db.query(models.UserAchievement).count() == 0
        assert db.query(models.AchievementReportDelivery).count() == 0
    finally:
        release_achievement_lease(blocker, tournament.id, token)
        blocker.close()

    assert await send_achievements_report(bot, db, tournament.id) == 1
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_lease_is_released_when_processing_raises(db, played, owner_chat, monkeypatch):
    tournament, _ = played

    async def fail(*_args, **_kwargs):
        raise RuntimeError("processing failed")

    monkeypatch.setattr("bot.telegram.achievements._send_achievements_report_locked", fail)

    with pytest.raises(RuntimeError, match="processing failed"):
        await send_achievements_report(AsyncMock(), db, tournament.id)

    assert db.get(models.AchievementProcessingLease, tournament.id) is None
