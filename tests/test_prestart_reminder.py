"""Tests for the pre-start deck reminder + registration-open deeplink message."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from bot.scheduler import PreStartReminderJob, get_clubs, send_registration_open
from core.config import Club, ClubSchedule
from core.schemas import TournamentCreate
from services.tournament import TournamentService

MONDAY = datetime(2026, 7, 13, 19, 25, tzinfo=ZoneInfo("Europe/Moscow"))  # понедельник
TUESDAY = datetime(2026, 7, 14, 19, 25, tzinfo=ZoneInfo("Europe/Moscow"))


def _bot():
    bot = AsyncMock()
    bot.get_me.return_value = MagicMock(username="TestBot")
    return bot


class TestSendRegistrationOpen:
    async def test_button_is_a_deck_deeplink(self, db, monkeypatch):
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", 777)
        club = Club(name="Edinorog", chat_id=-100, schedules=[])
        bot = _bot()

        await send_registration_open(bot, club, tournament_id=42, text="Регистрация открыта")

        # ушло и в чат клуба, и владельцу
        chats = {c.kwargs["chat_id"] for c in bot.send_message.call_args_list}
        assert chats == {-100, 777}
        button = bot.send_message.call_args_list[0].kwargs["reply_markup"].inline_keyboard[0][0]
        assert button.url == "https://t.me/TestBot?start=deck_42"

    async def test_skips_missing_chat_ids(self, db, monkeypatch):
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", None)
        club = Club(name="Edinorog", chat_id=0, schedules=[])  # нет ни группы, ни владельца
        bot = _bot()

        await send_registration_open(bot, club, tournament_id=1, text="x")

        bot.send_message.assert_not_awaited()


class TestPreStartReminderJob:
    def _club_schedule(self):
        club = Club(name="Edinorog", chat_id=-100, schedules=[])
        schedule = ClubSchedule(weekday="monday", game_time="19:30", reminder_time="19:25")
        return club, schedule

    async def test_reminds_when_active_tournament_exists(self, db, monkeypatch):
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", 777)
        club, schedule = self._club_schedule()
        TournamentService(db).create_tournament(TournamentCreate(title="Pauper", chat_id=-100))
        bot = _bot()

        await PreStartReminderJob(club, schedule).run(bot=bot, now=MONDAY, db=db)

        bot.send_message.assert_awaited()
        assert "начинается" in bot.send_message.call_args_list[0].kwargs["text"]

    async def test_silent_without_active_tournament(self, db):
        club, schedule = self._club_schedule()
        bot = _bot()

        await PreStartReminderJob(club, schedule).run(bot=bot, now=MONDAY, db=db)

        bot.send_message.assert_not_awaited()

    async def test_skips_wrong_weekday(self, db, monkeypatch):
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", 777)
        club, schedule = self._club_schedule()
        TournamentService(db).create_tournament(TournamentCreate(title="Pauper", chat_id=-100))
        bot = _bot()

        await PreStartReminderJob(club, schedule).run(bot=bot, now=TUESDAY, db=db)

        bot.send_message.assert_not_awaited()


class TestReminderSchedule:
    def test_configured_reminder_times(self):
        times = {(c.name, s.weekday): s.reminder_time for c in get_clubs() for s in c.schedules}
        assert times[("Goldfish", "thursday")] == "19:45"
        assert times[("Goldfish", "friday")] == "19:45"
        assert times[("Edinorog", "monday")] == "19:25"
        assert times[("Edinorog", "thursday")] == "19:25"
