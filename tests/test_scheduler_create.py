"""Tests for setup_scheduler with the Club/ClubSchedule API."""

from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from bot.scheduler import setup_scheduler
from core.config import Club, ClubSchedule

TZ = "Europe/Moscow"


def _make_app():
    app = MagicMock()
    app.job_queue = MagicMock()
    return app


def _mock_settings(create_time: str = "10:00"):
    s = MagicMock()
    s.TOURNAMENT_TIMEZONE = TZ
    s.TOURNAMENT_CREATE_TIME = create_time
    s.DEBUG = False
    return s


class TestSetupScheduler:
    def test_no_clubs_registers_no_jobs(self):
        app = _make_app()
        with patch("bot.scheduler.settings", _mock_settings()), patch("bot.scheduler.get_clubs", return_value=[]):
            setup_scheduler(app)
        app.job_queue.run_daily.assert_not_called()

    def test_one_schedule_no_fetch_times_registers_one_job(self):
        app = _make_app()
        clubs = [
            Club(
                name="Test",
                chat_id=1,
                schedules=[
                    ClubSchedule(weekday="friday", game_time="19:30"),
                ],
            )
        ]
        with patch("bot.scheduler.settings", _mock_settings()), patch("bot.scheduler.get_clubs", return_value=clubs):
            setup_scheduler(app)
        assert app.job_queue.run_daily.call_count == 1

    def test_fetch_times_register_extra_jobs(self):
        """Each aetherhub_fetch_time creates one extra import job."""
        app = _make_app()
        clubs = [
            Club(
                name="Goldfish",
                chat_id=1,
                aetherhub_url="https://aetherhub.com/User/GoldFish",
                schedules=[
                    ClubSchedule(
                        weekday="friday", game_time="19:30", aetherhub_fetch_times=["20:15", "21:00", "22:00"]
                    ),
                ],
            )
        ]
        with patch("bot.scheduler.settings", _mock_settings()), patch("bot.scheduler.get_clubs", return_value=clubs):
            setup_scheduler(app)
        # 1 create job + 3 import jobs = 4
        assert app.job_queue.run_daily.call_count == 4

    def test_two_schedules_register_two_create_jobs(self):
        """Club with two weekly schedules (fri + sat) gets a create job for each."""
        app = _make_app()
        clubs = [
            Club(
                name="Goldfish",
                chat_id=1,
                aetherhub_url="https://aetherhub.com/User/GoldFish",
                schedules=[
                    ClubSchedule(weekday="friday", game_time="19:30"),
                    ClubSchedule(weekday="saturday", game_time="14:00"),
                ],
            )
        ]
        with patch("bot.scheduler.settings", _mock_settings()), patch("bot.scheduler.get_clubs", return_value=clubs):
            setup_scheduler(app)
        # 2 create jobs, no fetch jobs
        assert app.job_queue.run_daily.call_count == 2

    def test_schedule_create_time_overrides_default(self):
        """ClubSchedule.create_time overrides TOURNAMENT_CREATE_TIME."""
        app = _make_app()
        clubs = [
            Club(
                name="Test",
                chat_id=1,
                schedules=[
                    ClubSchedule(weekday="monday", game_time="19:30", create_time="12:00"),
                ],
            )
        ]
        with (
            patch("bot.scheduler.settings", _mock_settings(create_time="10:00")),
            patch("bot.scheduler.get_clubs", return_value=clubs),
        ):
            setup_scheduler(app)
        scheduled_time = app.job_queue.run_daily.call_args.kwargs["time"]
        assert scheduled_time.hour == 12
        assert scheduled_time.minute == 0

    def test_default_create_time_used_when_schedule_has_none(self):
        app = _make_app()
        clubs = [
            Club(
                name="Test",
                chat_id=1,
                schedules=[
                    ClubSchedule(weekday="friday", game_time="19:30"),
                ],
            )
        ]
        with (
            patch("bot.scheduler.settings", _mock_settings(create_time="09:30")),
            patch("bot.scheduler.get_clubs", return_value=clubs),
        ):
            setup_scheduler(app)
        scheduled_time = app.job_queue.run_daily.call_args.kwargs["time"]
        assert scheduled_time.hour == 9
        assert scheduled_time.minute == 30

    def test_multiple_clubs_each_get_own_jobs(self):
        """Two clubs, one schedule each → 2 create jobs total."""
        app = _make_app()
        clubs = [
            Club(
                name="Goldfish",
                chat_id=101,
                schedules=[
                    ClubSchedule(weekday="friday", game_time="19:30"),
                ],
            ),
            Club(
                name="Edinorog",
                chat_id=102,
                schedules=[
                    ClubSchedule(weekday="monday", game_time="19:30"),
                ],
            ),
        ]
        with patch("bot.scheduler.settings", _mock_settings()), patch("bot.scheduler.get_clubs", return_value=clubs):
            setup_scheduler(app)
        assert app.job_queue.run_daily.call_count == 2

    def test_create_job_days_matches_weekday(self):
        """run_daily is called with days=(weekday_int,) matching the schedule."""
        app = _make_app()
        clubs = [
            Club(
                name="Test",
                chat_id=1,
                schedules=[
                    ClubSchedule(weekday="thursday", game_time="19:45", create_time="12:00"),
                ],
            )
        ]
        with patch("bot.scheduler.settings", _mock_settings()), patch("bot.scheduler.get_clubs", return_value=clubs):
            setup_scheduler(app)
        call_kwargs = app.job_queue.run_daily.call_args.kwargs
        assert call_kwargs["days"] == (3,)  # thursday = 3

    def test_import_job_days_matches_weekday(self):
        """Import jobs also get the correct days= parameter."""
        app = _make_app()
        clubs = [
            Club(
                name="Test",
                chat_id=1,
                aetherhub_url="https://aetherhub.com/User/Test",
                schedules=[
                    ClubSchedule(weekday="friday", game_time="19:45", aetherhub_fetch_times=["21:00"]),
                ],
            )
        ]
        with patch("bot.scheduler.settings", _mock_settings()), patch("bot.scheduler.get_clubs", return_value=clubs):
            setup_scheduler(app)
        # Both calls (create + import) should use days=(4,) for Friday
        for call in app.job_queue.run_daily.call_args_list:
            assert call.kwargs["days"] == (4,)  # friday = 4

    def test_goldfish_full_config_registers_correct_count(self):
        """Goldfish fri(1+3) + sat(1+2) + Edinorog mon(1) = 8 jobs."""
        app = _make_app()
        clubs = [
            Club(
                name="Goldfish",
                chat_id=1,
                aetherhub_url="https://aetherhub.com/User/GoldFish",
                schedules=[
                    ClubSchedule(
                        weekday="friday", game_time="19:30", aetherhub_fetch_times=["20:15", "21:00", "22:00"]
                    ),
                    ClubSchedule(weekday="saturday", game_time="14:00", aetherhub_fetch_times=["20:15", "21:00"]),
                ],
            ),
            Club(
                name="Edinorog",
                chat_id=2,
                schedules=[
                    ClubSchedule(weekday="monday", game_time="19:30", create_time="12:00"),
                ],
            ),
        ]
        with patch("bot.scheduler.settings", _mock_settings()), patch("bot.scheduler.get_clubs", return_value=clubs):
            setup_scheduler(app)
        assert app.job_queue.run_daily.call_count == 8
