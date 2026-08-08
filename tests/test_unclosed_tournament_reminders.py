from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from bot.scheduler import UnclosedTournamentReminderJob
from core import models
from core.config import settings
from core.schemas import TournamentCreate
from services.tournament import TournamentService

NOW = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)


def _tournament(db, svc, *, age: timedelta, chat_id: int = 100):
    tournament = svc.create_tournament(TournamentCreate(title="Old Pauper", chat_id=chat_id, slug=f"old-{chat_id}"))
    row = db.get(models.Tournament, tournament.id)
    row.created_at = NOW.replace(tzinfo=None) - age
    db.commit()
    return row


@pytest.mark.asyncio
async def test_sends_owner_only_reminder_after_three_days(db, svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    tournament = _tournament(db, svc, age=timedelta(days=3))
    bot = AsyncMock()

    await UnclosedTournamentReminderJob().run(bot, NOW, db=db)

    bot.send_message.assert_awaited_once()
    assert bot.send_message.call_args.kwargs["chat_id"] == 777
    text = bot.send_message.call_args.kwargs["text"]
    assert "не закрыт уже 3 дня" in text
    assert "Old Pauper" in text
    assert db.get(models.Tournament, tournament.id).unclosed_reminder_3d_sent_at is not None


@pytest.mark.asyncio
async def test_three_day_reminder_is_idempotent(db, svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    _tournament(db, svc, age=timedelta(days=4))
    bot = AsyncMock()
    job = UnclosedTournamentReminderJob()

    await job.run(bot, NOW, db=db)
    await job.run(bot, NOW, db=db)

    assert bot.send_message.await_count == 1


@pytest.mark.asyncio
async def test_sends_second_reminder_after_seven_days(db, svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    tournament = _tournament(db, svc, age=timedelta(days=7))
    tournament.unclosed_reminder_3d_sent_at = NOW.replace(tzinfo=None) - timedelta(days=4)
    db.commit()
    bot = AsyncMock()

    await UnclosedTournamentReminderJob().run(bot, NOW, db=db)

    assert "не закрыт уже 7 дней" in bot.send_message.call_args.kwargs["text"]
    assert db.get(models.Tournament, tournament.id).unclosed_reminder_7d_sent_at is not None


@pytest.mark.asyncio
async def test_overdue_tournament_gets_only_seven_day_reminder(db, svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    tournament = _tournament(db, svc, age=timedelta(days=8))
    bot = AsyncMock()

    await UnclosedTournamentReminderJob().run(bot, NOW, db=db)

    assert bot.send_message.await_count == 1
    assert "7 дней" in bot.send_message.call_args.kwargs["text"]
    row = db.get(models.Tournament, tournament.id)
    assert row.unclosed_reminder_3d_sent_at is not None
    assert row.unclosed_reminder_7d_sent_at is not None


@pytest.mark.asyncio
async def test_failed_delivery_is_retried(db, svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    tournament = _tournament(db, svc, age=timedelta(days=3))
    bot = AsyncMock()
    bot.send_message.side_effect = [RuntimeError("Telegram unavailable"), None]
    job = UnclosedTournamentReminderJob()

    await job.run(bot, NOW, db=db)
    assert db.get(models.Tournament, tournament.id).unclosed_reminder_3d_sent_at is None
    await job.run(bot, NOW, db=db)

    assert bot.send_message.await_count == 2
    assert db.get(models.Tournament, tournament.id).unclosed_reminder_3d_sent_at is not None


@pytest.mark.asyncio
async def test_ignores_recent_and_closed_tournaments(db, svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    _tournament(db, svc, age=timedelta(days=2, hours=23))
    old = _tournament(db, svc, age=timedelta(days=7), chat_id=200)
    TournamentService(db).close_tournament(old.id)
    bot = AsyncMock()

    await UnclosedTournamentReminderJob().run(bot, NOW, db=db)

    bot.send_message.assert_not_awaited()
