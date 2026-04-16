from datetime import time

import pytest

from bot.scheduler import parse_schedule


class TestParseSchedule:
    def test_friday_evening(self):
        weekday, t = parse_schedule("friday 19:00")
        assert weekday == 4
        assert t == time(19, 0)

    def test_monday_morning(self):
        weekday, t = parse_schedule("monday 09:30")
        assert weekday == 0
        assert t == time(9, 30)

    def test_sunday(self):
        weekday, t = parse_schedule("sunday 00:00")
        assert weekday == 6
        assert t == time(0, 0)

    def test_case_insensitive(self):
        weekday, t = parse_schedule("FRIDAY 19:00")
        assert weekday == 4

    def test_invalid_day_raises(self):
        with pytest.raises(ValueError, match="Unknown weekday"):
            parse_schedule("funday 19:00")

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid schedule format"):
            parse_schedule("friday")

    def test_invalid_time_raises(self):
        with pytest.raises(ValueError):
            parse_schedule("friday 25:00")
