"""Tests for _create_tournaments_for_schedule and setup_scheduler."""

import asyncio
from datetime import datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import core.models  # noqa: F401
from bot.scheduler import _create_tournaments_for_schedule, _make_job, setup_scheduler
from core.database import Base
from core.models import TournamentStatus
from core.models import Tournament as TournamentModel
from core.schemas import TournamentCreate
from services.tournament import TournamentService

TZ = "Europe/Moscow"
CHAT_ID = 42


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def set_fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    return Session(engine)


def _make_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


def _patch_settings(schedule: str = "friday 19:00", chat_ids=None):
    mock_settings = MagicMock()
    mock_settings.TOURNAMENT_TIMEZONE = TZ
    mock_settings.chat_ids = chat_ids if chat_ids is not None else [CHAT_ID]
    mock_settings.schedule_list = [schedule]
    return patch("bot.scheduler.settings", mock_settings)


def _patch_now(weekday: int, hour: int = 19, minute: int = 0):
    """Patch datetime.now inside bot.scheduler to return a fixed datetime with given weekday."""
    tz = ZoneInfo(TZ)
    anchor = datetime(2024, 1, 1, hour, minute, tzinfo=tz)  # Monday (weekday=0)
    delta = (weekday - anchor.weekday()) % 7
    fixed = anchor + timedelta(days=delta)

    mock_dt = MagicMock(wraps=datetime)
    mock_dt.now = MagicMock(return_value=fixed)
    mock_dt.strptime = datetime.strptime
    return patch("bot.scheduler.datetime", mock_dt)


# ---------------------------------------------------------------------------
# Tests for _create_tournaments_for_schedule
# ---------------------------------------------------------------------------

class TestCreateTournamentsForSchedule:

    def test_wrong_weekday_skips(self):
        """Should return early without touching the DB on a wrong weekday."""
        db = _make_db()
        bot = _make_bot()

        # schedule says friday (4), but we mock now as saturday (5)
        with _patch_settings("friday 19:00", chat_ids=[CHAT_ID]), \
             _patch_now(weekday=5), \
             patch("bot.scheduler.SessionLocal", return_value=db):
            asyncio.run(_create_tournaments_for_schedule(bot, "friday 19:00"))

        bot.send_message.assert_not_called()
        svc = TournamentService(db)
        assert svc.get_active_tournament_for_chat(CHAT_ID) is None
        db.close()

    def test_correct_weekday_creates_tournament(self):
        """Should create a tournament and send an announcement on the right day."""
        db = _make_db()
        bot = _make_bot()

        with _patch_settings("friday 19:00", chat_ids=[CHAT_ID]), \
             _patch_now(weekday=4), \
             patch("bot.scheduler.SessionLocal", return_value=db):
            asyncio.run(_create_tournaments_for_schedule(bot, "friday 19:00"))

        bot.send_message.assert_awaited_once()
        call_kwargs = bot.send_message.await_args.kwargs
        assert call_kwargs["chat_id"] == CHAT_ID
        assert "Pauper" in call_kwargs["text"]

        svc = TournamentService(db)
        active = svc.get_active_tournament_for_chat(CHAT_ID)
        assert active is not None
        assert active.status == TournamentStatus.REGISTRATION
        db.close()

    def test_correct_weekday_closes_existing_then_creates(self):
        """Should close an existing active tournament before creating a new one."""
        db = _make_db()
        bot = _make_bot()
        svc = TournamentService(db)
        old = svc.create_tournament(TournamentCreate(title="Old", chat_id=CHAT_ID, slug="old"))

        with _patch_settings("friday 19:00", chat_ids=[CHAT_ID]), \
             _patch_now(weekday=4), \
             patch("bot.scheduler.SessionLocal", return_value=db):
            asyncio.run(_create_tournaments_for_schedule(bot, "friday 19:00"))

        old_orm = db.get(TournamentModel, old.id)
        assert old_orm.status == TournamentStatus.CLOSED

        active = svc.get_active_tournament_for_chat(CHAT_ID)
        assert active is not None
        assert active.id != old.id
        bot.send_message.assert_awaited_once()
        db.close()

    def test_empty_chat_ids_skips(self):
        """Should log a warning and skip when no chat IDs are configured."""
        db = _make_db()
        bot = _make_bot()

        with _patch_settings("friday 19:00", chat_ids=[]), \
             _patch_now(weekday=4), \
             patch("bot.scheduler.SessionLocal", return_value=db):
            asyncio.run(_create_tournaments_for_schedule(bot, "friday 19:00"))

        bot.send_message.assert_not_called()
        db.close()

    def test_per_chat_exception_does_not_abort_others(self):
        """An error for one chat should not prevent processing of the next chat."""
        chat_a, chat_b = 101, 102
        db = _make_db()
        bot = _make_bot()

        async def send_message_side_effect(chat_id, text):
            if chat_id == chat_a:
                raise RuntimeError("Network error")

        bot.send_message.side_effect = send_message_side_effect

        with _patch_settings("friday 19:00", chat_ids=[chat_a, chat_b]), \
             _patch_now(weekday=4), \
             patch("bot.scheduler.SessionLocal", return_value=db):
            asyncio.run(_create_tournaments_for_schedule(bot, "friday 19:00"))

        svc = TournamentService(db)
        assert svc.get_active_tournament_for_chat(chat_b) is not None
        db.close()

    def test_multiple_chats_all_get_tournaments(self):
        """Each configured chat should receive its own tournament."""
        chat_ids = [201, 202, 203]
        db = _make_db()
        bot = _make_bot()

        with _patch_settings("friday 19:00", chat_ids=chat_ids), \
             _patch_now(weekday=4), \
             patch("bot.scheduler.SessionLocal", return_value=db):
            asyncio.run(_create_tournaments_for_schedule(bot, "friday 19:00"))

        svc = TournamentService(db)
        for cid in chat_ids:
            assert svc.get_active_tournament_for_chat(cid) is not None
        assert bot.send_message.await_count == len(chat_ids)
        db.close()


# ---------------------------------------------------------------------------
# Tests for _make_job
# ---------------------------------------------------------------------------

class TestMakeJob:

    def test_job_calls_create_tournaments(self):
        """_make_job should return a coroutine that delegates to _create_tournaments_for_schedule."""
        context = MagicMock()
        context.bot = _make_bot()

        with patch("bot.scheduler._create_tournaments_for_schedule", new_callable=AsyncMock) as mock_create:
            job = _make_job("friday 19:00")
            asyncio.run(job(context))
            mock_create.assert_awaited_once_with(context.bot, "friday 19:00")

    def test_job_name_contains_schedule_entry(self):
        job = _make_job("saturday 12:00")
        assert "saturday 12:00" in job.__name__


# ---------------------------------------------------------------------------
# Tests for setup_scheduler
# ---------------------------------------------------------------------------

class TestSetupScheduler:

    def test_registers_one_job_per_schedule_entry(self):
        """setup_scheduler should call run_daily once for each entry in schedule_list."""
        app = MagicMock()
        app.job_queue = MagicMock()

        mock_settings = MagicMock()
        mock_settings.TOURNAMENT_TIMEZONE = TZ
        mock_settings.schedule_list = ["friday 19:00", "saturday 12:00"]
        mock_settings.chat_ids = [CHAT_ID]

        with patch("bot.scheduler.settings", mock_settings):
            setup_scheduler(app)

        assert app.job_queue.run_daily.call_count == 2

    def test_registers_correct_time(self):
        """run_daily should be called with the time= kwarg parsed from the schedule entry."""
        app = MagicMock()
        app.job_queue = MagicMock()

        mock_settings = MagicMock()
        mock_settings.TOURNAMENT_TIMEZONE = TZ
        mock_settings.schedule_list = ["friday 19:00"]
        mock_settings.chat_ids = [CHAT_ID]

        with patch("bot.scheduler.settings", mock_settings):
            setup_scheduler(app)

        call_kwargs = app.job_queue.run_daily.call_args.kwargs
        scheduled_time = call_kwargs["time"]
        assert scheduled_time.hour == 19
        assert scheduled_time.minute == 0
