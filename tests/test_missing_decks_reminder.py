from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from bot.scheduler import MissingDecksReminderJob
from core import models
from core.schemas import TournamentCreate
from services.tournament import TournamentService

MOSCOW = ZoneInfo("Europe/Moscow")
EVENT_AT = datetime(2026, 8, 14, 19, 30, tzinfo=MOSCOW)
DAY_ONE = datetime(2026, 8, 15, 15, 0, tzinfo=MOSCOW)
DAY_THREE = datetime(2026, 8, 17, 15, 0, tzinfo=MOSCOW)


def _bot():
    bot = AsyncMock()
    bot.get_me.return_value = MagicMock(username="TestBot")
    return bot


def _tournament(db, svc, *, chat_id: int = 100, event_at: datetime = EVENT_AT):
    tournament = svc.create_tournament(
        TournamentCreate(
            title="Goldfish Pauper 14.08.2026",
            chat_id=chat_id,
            slug=f"missing-{chat_id}",
            registration_close_at=event_at.astimezone(timezone.utc).replace(tzinfo=None),
        )
    )
    return db.get(models.Tournament, tournament.id)


@pytest.mark.asyncio
async def test_sends_meta_police_to_tournament_chat_with_missing_players_and_registration_button(
    db, svc, user_svc, user_alice, archetype_burn
):
    tournament = _tournament(db, svc)
    missing_user = user_svc.get_or_create(tg_id=2001, username="missing", first_name="Глеб", last_name="Лактанов")
    svc.register_participant(tournament_id=tournament.id, user_id=missing_user.id)
    svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
    bot = _bot()

    await MissingDecksReminderJob().run(bot, DAY_ONE, db=db)

    bot.send_message.assert_awaited_once()
    assert bot.send_message.call_args.kwargs["chat_id"] == 100
    text = bot.send_message.call_args.kwargs["text"]
    assert text.startswith("🚨👮 Вас посетила мета-полиция!")
    assert "На какой колоде были эти игроки?" in text
    assert "Список игроков без колоды:" in text
    assert "• Лактанов Глеб (@missing)" in text
    assert "Alice" not in text
    button = bot.send_message.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.text == "Записаться"
    assert button.url == f"https://t.me/TestBot?start=register_{tournament.id}"
    row = db.get(models.Tournament, tournament.id)
    assert row.missing_decks_reminder_1d_sent_at is not None


@pytest.mark.asyncio
async def test_reminder_is_sent_only_once(db, svc, user_alice):
    tournament = _tournament(db, svc)
    svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
    bot = _bot()
    job = MissingDecksReminderJob()

    await job.run(bot, DAY_ONE, db=db)
    await job.run(bot, DAY_ONE, db=db)
    await job.run(bot, DAY_THREE, db=db)

    bot.send_message.assert_awaited_once()
    assert db.get(models.Tournament, tournament.id).missing_decks_reminder_1d_sent_at is not None


@pytest.mark.asyncio
async def test_overdue_first_reminder_is_sent_once(db, svc, user_alice):
    tournament = _tournament(db, svc)
    svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
    bot = _bot()
    job = MissingDecksReminderJob()

    await job.run(bot, DAY_THREE, db=db)
    await job.run(bot, DAY_THREE, db=db)

    bot.send_message.assert_awaited_once()
    assert db.get(models.Tournament, tournament.id).missing_decks_reminder_1d_sent_at is not None


@pytest.mark.asyncio
async def test_failed_delivery_is_retried(db, svc, user_alice):
    tournament = _tournament(db, svc)
    svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
    bot = _bot()
    bot.send_message.side_effect = [RuntimeError("Telegram unavailable"), None]
    job = MissingDecksReminderJob()

    await job.run(bot, DAY_ONE, db=db)
    assert db.get(models.Tournament, tournament.id).missing_decks_reminder_1d_sent_at is None
    await job.run(bot, DAY_ONE, db=db)

    assert bot.send_message.await_count == 2
    assert db.get(models.Tournament, tournament.id).missing_decks_reminder_1d_sent_at is not None


@pytest.mark.asyncio
async def test_get_me_failure_is_retried_without_sending_buttonless_message(db, svc, user_alice):
    tournament = _tournament(db, svc)
    svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
    bot = _bot()
    bot.get_me.side_effect = [RuntimeError("Telegram unavailable"), MagicMock(username="TestBot")]
    job = MissingDecksReminderJob()

    await job.run(bot, DAY_ONE, db=db)
    assert db.get(models.Tournament, tournament.id).missing_decks_reminder_1d_sent_at is None
    bot.send_message.assert_not_awaited()
    await job.run(bot, DAY_ONE, db=db)

    bot.send_message.assert_awaited_once()
    assert db.get(models.Tournament, tournament.id).missing_decks_reminder_1d_sent_at is not None


@pytest.mark.asyncio
async def test_ignores_tournament_on_event_day(db, svc, user_alice):
    tournament = _tournament(db, svc)
    svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
    bot = _bot()

    await MissingDecksReminderJob().run(bot, EVENT_AT, db=db)

    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_ignores_closed_tournament_and_tournament_with_all_decks(
    db, svc, user_svc, user_alice, archetype_burn
):
    complete = _tournament(db, svc)
    svc.register_participant(tournament_id=complete.id, user_id=user_alice.id, archetype_id=archetype_burn.id)

    closed = _tournament(db, svc, chat_id=200)
    missing_user = user_svc.get_or_create(tg_id=2002, username="closed", first_name="Closed")
    svc.register_participant(tournament_id=closed.id, user_id=missing_user.id)
    TournamentService(db).close_tournament(closed.id)
    bot = _bot()

    await MissingDecksReminderJob().run(bot, DAY_ONE, db=db)
    await MissingDecksReminderJob().run(bot, DAY_THREE, db=db)

    bot.send_message.assert_not_awaited()
