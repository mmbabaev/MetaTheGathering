"""Tests for setup_scheduler with the Club/ClubSchedule API."""

from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from bot.scheduler import _import_day_offset, _ptb_day, reload_schedule_jobs, setup_scheduler
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
        assert app.job_queue.run_daily.call_count == 6  # 3 final-reimports + 3 global jobs
        final_times = [call.kwargs["time"] for call in app.job_queue.run_daily.call_args_list[:3]]
        assert [(value.hour, value.minute) for value in final_times] == [(9, 0), (12, 0), (18, 0)]
        callbacks = [call.args[0].__name__ for call in app.job_queue.run_daily.call_args_list[:3]]
        assert callbacks == [
            "aetherhub_final_reimport[09:00]",
            "aetherhub_final_reimport[12:00]",
            "aetherhub_final_reimport[18:00]",
        ]
        jobs = {call.args[0].__name__: call for call in app.job_queue.run_daily.call_args_list}
        unclosed_call = jobs["unclosed_tournament_reminders"]
        assert (unclosed_call.kwargs["time"].hour, unclosed_call.kwargs["time"].minute) == (10, 0)
        missing_decks_call = jobs["missing_decks_reminder"]
        assert (missing_decks_call.kwargs["time"].hour, missing_decks_call.kwargs["time"].minute) == (15, 0)

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
        assert app.job_queue.run_daily.call_count == 7  # 1 create + 3 final-reimports + 3 global jobs

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
        # 1 create + 3 import + 3 final-reimports + 3 global jobs = 10
        assert app.job_queue.run_daily.call_count == 10

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
        # 2 create + 3 final-reimports + 3 global jobs = 8
        assert app.job_queue.run_daily.call_count == 8

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
        scheduled_time = app.job_queue.run_daily.call_args_list[0].kwargs["time"]
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
        scheduled_time = app.job_queue.run_daily.call_args_list[0].kwargs["time"]
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
        assert app.job_queue.run_daily.call_count == 8  # 2 create + 3 final-reimports + 3 global jobs

    def test_club_jobs_use_club_local_timezone(self):
        app = _make_app()
        clubs = [
            Club(
                name="Hobby Games",
                chat_id=1,
                timezone="Europe/Kaliningrad",
                schedules=[
                    ClubSchedule(
                        weekday="saturday",
                        game_time="17:00",
                        create_time="18:30",
                        create_days_before=1,
                        reminder_time="16:55",
                    )
                ],
            )
        ]

        with patch("bot.scheduler.settings", _mock_settings()), patch("bot.scheduler.get_clubs", return_value=clubs):
            setup_scheduler(app)

        create_call, reminder_call = app.job_queue.run_daily.call_args_list[:2]
        assert create_call.kwargs["days"] == (5,)  # Friday opens registration for Saturday
        assert create_call.kwargs["time"].tzinfo == ZoneInfo("Europe/Kaliningrad")
        assert reminder_call.kwargs["days"] == (6,)
        assert reminder_call.kwargs["time"].tzinfo == ZoneInfo("Europe/Kaliningrad")

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
        call_kwargs = app.job_queue.run_daily.call_args_list[0].kwargs
        assert call_kwargs["days"] == (4,)  # thursday = 4 in PTB (0=Sunday)

    @pytest.mark.parametrize(
        "weekday, expected_create_day, expected_event_day",
        [
            ("tuesday", 1, 2),  # Monday creates Tuesday's event
            ("sunday", 6, 0),  # Saturday creates Sunday's event, across week boundary
        ],
    )
    def test_creation_runs_previous_day_but_reminder_and_import_stay_on_event_day(
        self, weekday, expected_create_day, expected_event_day
    ):
        app = _make_app()
        clubs = [
            Club(
                name="Pair of dice",
                chat_id=1,
                aetherhub_url="https://aetherhub.com/User/Andysays",
                schedules=[
                    ClubSchedule(
                        weekday=weekday,
                        game_time="19:30",
                        create_time="18:30",
                        create_days_before=1,
                        reminder_time="19:25",
                        aetherhub_fetch_times=["20:00"],
                    )
                ],
            )
        ]

        with patch("bot.scheduler.settings", _mock_settings()), patch("bot.scheduler.get_clubs", return_value=clubs):
            setup_scheduler(app)

        create_call, reminder_call, import_call = app.job_queue.run_daily.call_args_list[:3]
        assert create_call.kwargs["days"] == (expected_create_day,)
        assert reminder_call.kwargs["days"] == (expected_event_day,)
        assert import_call.kwargs["days"] == (expected_event_day,)

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
        # Both calls (create + import) should use days=(5,) for Friday in PTB (0=Sunday)
        for call in app.job_queue.run_daily.call_args_list:
            if "days" not in call.kwargs:  # skip daily final-reimport / reveal-decks
                continue
            assert call.kwargs["days"] == (5,)  # friday = 5 in PTB (0=Sunday)

    def test_import_times_after_midnight_run_on_next_calendar_day(self):
        app = _make_app()
        clubs = [
            Club(
                name="Test",
                chat_id=1,
                aetherhub_url="https://aetherhub.com/User/Test",
                schedules=[
                    ClubSchedule(
                        weekday="friday",
                        game_time="19:45",
                        aetherhub_fetch_times=["23:30", "00:00", "00:30"],
                    )
                ],
            )
        ]

        with patch("bot.scheduler.settings", _mock_settings()), patch("bot.scheduler.get_clubs", return_value=clubs):
            setup_scheduler(app)

        import_calls = app.job_queue.run_daily.call_args_list[1:4]
        assert [call.kwargs["days"] for call in import_calls] == [(5,), (6,), (6,)]

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
        assert app.job_queue.run_daily.call_count == 14  # 8 + 3 final-reimports + 3 global jobs


# ---------------------------------------------------------------------------
# _ptb_day: PTB uses 0=Sunday, Python weekday uses 0=Monday
# ---------------------------------------------------------------------------


class TestPtbDay:
    @pytest.mark.parametrize(
        "weekday, expected",
        [
            ("monday", 1),
            ("tuesday", 2),
            ("wednesday", 3),
            ("thursday", 4),
            ("friday", 5),
            ("saturday", 6),
            ("sunday", 0),  # wraps: (6+1) % 7 == 0
        ],
    )
    def test_all_weekdays(self, weekday, expected):
        assert _ptb_day(weekday) == expected

    def test_sunday_wraps_to_zero(self):
        assert _ptb_day("sunday") == 0

    def test_thursday_is_4_not_3(self):
        """The original bug: thursday was passing days=(3,) which PTB treated as Wednesday."""
        assert _ptb_day("thursday") == 4

    def test_friday_is_5_not_4(self):
        assert _ptb_day("friday") == 5

    def test_create_job_uses_ptb_day(self):
        """setup_scheduler passes the PTB-correct day value to run_daily."""
        app = _make_app()
        clubs = [
            Club(
                name="T",
                chat_id=1,
                schedules=[ClubSchedule(weekday="sunday", game_time="10:00", create_time="10:00")],
            )
        ]
        with patch("bot.scheduler.settings", _mock_settings()), patch("bot.scheduler.get_clubs", return_value=clubs):
            setup_scheduler(app)
        call_kwargs = app.job_queue.run_daily.call_args_list[0].kwargs
        assert call_kwargs["days"] == (0,)  # sunday = 0 in PTB


class TestImportDayOffset:
    def test_detects_midnight_rollover_from_sequence(self):
        times = ["23:30", "00:00", "00:30"]
        assert _import_day_offset(times, "23:30") == 0
        assert _import_day_offset(times, "00:00") == 1
        assert _import_day_offset(times, "00:30") == 1

    def test_midnight_only_sequence_stays_on_scheduled_day(self):
        assert _import_day_offset(["00:00", "00:30"], "00:00") == 0


# ── reload_schedule_jobs: правка расписания применяется без рестарта (issue #124) ──


class _FakeJob:
    def __init__(self, name):
        self.name = name
        self.removed = False

    def schedule_removal(self):
        self.removed = True


class TestReloadScheduleJobs:
    def _clubs(self):
        return [
            Club(
                name="Test",
                chat_id=1,
                schedules=[ClubSchedule(weekday="friday", game_time="19:30", reminder_time="19:25")],
            )
        ]

    def test_removes_only_schedule_jobs(self):
        jobs = [
            _FakeJob("create_tournament[Test/friday]"),
            _FakeJob("prestart_reminder[Test/friday]"),
            _FakeJob("aetherhub_import[Test/friday/20:00]"),
            _FakeJob("aetherhub_final_reimport"),  # глобальная — не трогаем
            _FakeJob("auto_reveal_decks"),  # глобальная — не трогаем
        ]
        app = _make_app()
        app.job_queue.jobs.return_value = jobs

        with patch("bot.scheduler.settings", _mock_settings()), patch("bot.scheduler.get_clubs", return_value=[]):
            removed = reload_schedule_jobs(app)

        assert removed == 3
        assert [j.name for j in jobs if j.removed] == [
            "create_tournament[Test/friday]",
            "prestart_reminder[Test/friday]",
            "aetherhub_import[Test/friday/20:00]",
        ]
        assert not jobs[3].removed
        assert not jobs[4].removed

    def test_reregisters_from_current_clubs(self):
        app = _make_app()
        app.job_queue.jobs.return_value = []

        with (
            patch("bot.scheduler.settings", _mock_settings()),
            patch("bot.scheduler.get_clubs", return_value=self._clubs()),
        ):
            reload_schedule_jobs(app)

        # создание + напоминание, глобальные джобы при перезагрузке не трогаются
        assert app.job_queue.run_daily.call_count == 2
        assert app.job_queue.run_repeating.call_count == 0

    def test_disabled_schedule_registers_nothing(self):
        app = _make_app()
        app.job_queue.jobs.return_value = [_FakeJob("create_tournament[Test/friday]")]

        # get_clubs отдаёт клуб без расписаний — так выглядит выключенная строка
        clubs = [Club(name="Test", chat_id=1, schedules=[])]
        with patch("bot.scheduler.settings", _mock_settings()), patch("bot.scheduler.get_clubs", return_value=clubs):
            removed = reload_schedule_jobs(app)

        assert removed == 1
        assert app.job_queue.run_daily.call_count == 0
