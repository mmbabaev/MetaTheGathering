from unittest.mock import AsyncMock

from telegram.error import BadRequest

from bot.registration_messages import RegistrationMessageRefreshJob
from core import models
from core.schemas import TournamentCreate
from services.registration_message import RegistrationMessageService, format_registration_message
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.tournament import TournamentService


def _tournament(db, chat_id=100):
    return TournamentService(db).create_tournament(TournamentCreate(title="Pauper", chat_id=chat_id))


def test_format_registration_message_normalizes_trailing_newlines():
    assert format_registration_message("Регистрация открыта\n\n", 0) == "Регистрация открыта\n\nЗаписалось: 0"


def test_upsert_replaces_latest_message_for_target(db):
    tournament = _tournament(db)
    service = RegistrationMessageService(db)
    first = service.upsert_last(
        tournament_id=tournament.id,
        chat_id=100,
        message_id=10,
        base_text="Первое",
        button_url=None,
        participant_count=0,
    )
    second = service.upsert_last(
        tournament_id=tournament.id,
        chat_id=100,
        message_id=11,
        base_text="Новое",
        button_url="https://example.invalid",
        participant_count=0,
    )
    assert first.id == second.id
    assert second.message_id == 11
    assert db.query(models.TournamentRegistrationMessage).count() == 1


def test_list_stale_active_uses_real_participant_count(db, user_alice):
    tournament = _tournament(db)
    service = RegistrationMessageService(db)
    row = service.upsert_last(
        tournament_id=tournament.id,
        chat_id=100,
        message_id=10,
        base_text="Регистрация",
        button_url=None,
        participant_count=0,
    )
    TournamentService(db).register_participant(tournament_id=tournament.id, user_id=user_alice.id)
    assert service.list_stale_active() == [(row, 1)]


def test_closed_and_disabled_rows_are_not_stale(db, user_alice):
    tournament = _tournament(db)
    service = RegistrationMessageService(db)
    row = service.upsert_last(
        tournament_id=tournament.id,
        chat_id=100,
        message_id=10,
        base_text="Регистрация",
        button_url=None,
        participant_count=0,
    )
    TournamentService(db).register_participant(tournament_id=tournament.id, user_id=user_alice.id)
    service.disable(row.id, row.message_id)
    assert service.list_stale_active() == []
    row.edit_disabled_at = None
    db.commit()
    TournamentService(db).close_tournament(tournament.id)
    assert service.list_stale_active() == []


async def test_refresh_edits_stale_message(db, user_alice):
    FeatureFlagService(db).toggle(FeatureFlags.LIVE_REGISTRATION_COUNT)
    tournament = _tournament(db)
    service = RegistrationMessageService(db)
    row = service.upsert_last(
        tournament_id=tournament.id,
        chat_id=100,
        message_id=10,
        base_text="Регистрация",
        button_url=None,
        participant_count=0,
    )
    TournamentService(db).register_participant(tournament_id=tournament.id, user_id=user_alice.id)
    bot = AsyncMock()
    await RegistrationMessageRefreshJob().run(bot, db=db)
    bot.edit_message_text.assert_awaited_once()
    assert "Записалось: 1" in bot.edit_message_text.call_args.kwargs["text"]
    db.refresh(row)
    assert row.rendered_participant_count == 1


async def test_permanent_edit_error_disables_row(db, user_alice):
    FeatureFlagService(db).toggle(FeatureFlags.LIVE_REGISTRATION_COUNT)
    tournament = _tournament(db)
    service = RegistrationMessageService(db)
    row = service.upsert_last(
        tournament_id=tournament.id,
        chat_id=100,
        message_id=10,
        base_text="Регистрация",
        button_url=None,
        participant_count=0,
    )
    TournamentService(db).register_participant(tournament_id=tournament.id, user_id=user_alice.id)
    bot = AsyncMock()
    bot.edit_message_text.side_effect = BadRequest("Message to edit not found")
    await RegistrationMessageRefreshJob().run(bot, db=db)
    db.refresh(row)
    assert row.edit_disabled_at is not None


async def test_message_not_modified_marks_count_rendered(db, user_alice):
    FeatureFlagService(db).toggle(FeatureFlags.LIVE_REGISTRATION_COUNT)
    tournament = _tournament(db)
    service = RegistrationMessageService(db)
    row = service.upsert_last(
        tournament_id=tournament.id,
        chat_id=100,
        message_id=10,
        base_text="Регистрация",
        button_url=None,
        participant_count=0,
    )
    TournamentService(db).register_participant(tournament_id=tournament.id, user_id=user_alice.id)
    bot = AsyncMock()
    bot.edit_message_text.side_effect = BadRequest("Message is not modified")
    await RegistrationMessageRefreshJob().run(bot, db=db)
    db.refresh(row)
    assert row.rendered_participant_count == 1


async def test_disabled_flag_does_not_edit_stale_message(db, user_alice):
    tournament = _tournament(db)
    service = RegistrationMessageService(db)
    service.upsert_last(
        tournament_id=tournament.id,
        chat_id=100,
        message_id=10,
        base_text="Регистрация",
        button_url=None,
        participant_count=0,
    )
    TournamentService(db).register_participant(tournament_id=tournament.id, user_id=user_alice.id)

    bot = AsyncMock()
    await RegistrationMessageRefreshJob().run(bot, db=db)

    bot.edit_message_text.assert_not_awaited()
