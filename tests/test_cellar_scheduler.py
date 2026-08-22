from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from bot.scheduler import CellarCatalogSyncJob, CellarCoordinatorReminderJob, CreateTournamentJob
from core import models
from core.config import Club, ClubSchedule, settings
from core.schemas import TournamentCreate
from services.cellar import CellarService
from services.cellar_sheet import CatalogEntry
from services.tournament import TournamentService


def _reserve(db, user_svc, event_date=date(2026, 8, 24)):
    service = CellarService(db)
    service.ensure_bootstrap_catalog()
    deck = service.catalog(event_date)[0]
    user = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    reservation = service.reserve(
        deck_id=deck.id,
        user_id=user.id,
        event_date=event_date,
        today=event_date,
    ).reservation
    return reservation


@pytest.mark.asyncio
async def test_weekly_catalog_job_syncs_sheet_rows(db):
    class Source:
        def fetch(self):
            return [
                CatalogEntry(
                    "gsheet:altar:1",
                    "Altar Tron",
                    "Altar Tron",
                    decklist_url="https://example.test/altar",
                    source_position=13,
                )
            ]

    assert await CellarCatalogSyncJob(Source()).run(db=db) == (1, 0, 0)
    deck = CellarService(db).catalog(date(2026, 8, 24))[0]
    assert deck.display_name == "Altar Tron · №13"
    assert deck.decklist_url == "https://example.test/altar"


@pytest.mark.asyncio
async def test_create_tournament_attaches_pending_cellar_reservation(db, user_svc):
    event_date = date(2026, 8, 24)
    reservation = _reserve(db, user_svc, event_date)
    club = Club(
        name="Edinorog",
        chat_id=100,
        schedules=[],
        title_prefix="🦄 ",
        timezone="Europe/Moscow",
    )
    schedule = ClubSchedule(weekday="monday", game_time="19:30", create_time="12:00")

    await CreateTournamentJob(club, schedule).run(
        bot=None,
        now=datetime(2026, 8, 24, 12, 0, tzinfo=timezone(timedelta(hours=3))),
        db=db,
    )

    tournament = TournamentService(db).get_active_tournament_for_chat(100)
    assert tournament is not None
    assert reservation.tournament_id == tournament.id
    assert TournamentService(db).get_participant(tournament.id, reservation.user_id) is not None


@pytest.mark.asyncio
async def test_coordinator_summary_is_targeted_and_idempotent(db, user_svc, monkeypatch):
    event_date = date(2026, 8, 24)
    _reserve(db, user_svc, event_date)
    now = datetime(2026, 8, 24, 16, 16, tzinfo=timezone.utc)
    TournamentService(db).create_tournament(
        TournamentCreate(
            title="Edinorog",
            chat_id=100,
            club="Edinorog",
            registration_close_at=now.replace(tzinfo=None) + timedelta(minutes=14),
        )
    )
    monkeypatch.setattr(settings, "CELLAR_COORDINATOR_TG_IDS", "111,222")
    bot = AsyncMock()
    job = CellarCoordinatorReminderJob()

    await job.run(bot, now=now, db=db)
    await job.run(bot, now=now + timedelta(minutes=1), db=db)

    assert [call.kwargs["chat_id"] for call in bot.send_message.await_args_list] == [111, 222]
    assert all("Alice" in call.kwargs["text"] for call in bot.send_message.await_args_list)
    deliveries = db.execute(select(models.CellarCoordinatorReminder)).scalars().all()
    assert len(deliveries) == 2
    assert all(delivery.delivered_at is not None for delivery in deliveries)


@pytest.mark.asyncio
async def test_failed_coordinator_delivery_retries_without_resending_success(db, user_svc, monkeypatch):
    event_date = date(2026, 8, 24)
    _reserve(db, user_svc, event_date)
    now = datetime(2026, 8, 24, 16, 16, tzinfo=timezone.utc)
    TournamentService(db).create_tournament(
        TournamentCreate(
            title="Edinorog",
            chat_id=100,
            club="Edinorog",
            registration_close_at=now.replace(tzinfo=None) + timedelta(minutes=14),
        )
    )
    monkeypatch.setattr(settings, "CELLAR_COORDINATOR_TG_IDS", "111,222")
    bot = AsyncMock()
    failed_once = False

    async def send_message(*, chat_id, text):
        nonlocal failed_once
        if chat_id == 222 and not failed_once:
            failed_once = True
            raise RuntimeError("temporary")

    bot.send_message.side_effect = send_message
    job = CellarCoordinatorReminderJob()

    await job.run(bot, now=now, db=db)
    await job.run(bot, now=now + timedelta(minutes=1), db=db)

    recipients = [call.kwargs["chat_id"] for call in bot.send_message.await_args_list]
    assert recipients == [111, 222, 222]
    deliveries = db.execute(
        select(models.CellarCoordinatorReminder).order_by(models.CellarCoordinatorReminder.recipient_tg_id)
    ).scalars()
    assert [(row.recipient_tg_id, row.attempts, row.delivered_at is not None) for row in deliveries] == [
        (111, 1, True),
        (222, 2, True),
    ]


@pytest.mark.asyncio
async def test_coordinator_summary_is_not_sent_early(db, user_svc, monkeypatch):
    _reserve(db, user_svc)
    now = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)
    TournamentService(db).create_tournament(
        TournamentCreate(
            title="Edinorog",
            chat_id=100,
            club="Edinorog",
            registration_close_at=now.replace(tzinfo=None) + timedelta(minutes=30),
        )
    )
    monkeypatch.setattr(settings, "CELLAR_COORDINATOR_TG_IDS", "111,222")
    bot = AsyncMock()

    await CellarCoordinatorReminderJob().run(bot, now=now, db=db)

    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_coordinator_summary_respects_debug_allow_list(db, user_svc, monkeypatch):
    _reserve(db, user_svc)
    now = datetime(2026, 8, 24, 16, 16, tzinfo=timezone.utc)
    TournamentService(db).create_tournament(
        TournamentCreate(
            title="Edinorog",
            chat_id=100,
            club="Edinorog",
            registration_close_at=now.replace(tzinfo=None) + timedelta(minutes=14),
        )
    )
    monkeypatch.setattr(settings, "CELLAR_COORDINATOR_TG_IDS", "111,222")
    monkeypatch.setattr("core.config._app_cfg.notify_allowed_ids", [111])
    bot = AsyncMock()

    await CellarCoordinatorReminderJob().run(bot, now=now, db=db)

    assert [call.kwargs["chat_id"] for call in bot.send_message.await_args_list] == [111]
