"""Tests for the pre-start deck reminder + registration-open deeplink message."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from telegram.error import TelegramError

from bot.scheduler import PreStartReminderJob, get_clubs, send_registration_open
from core import models
from core.config import Club, ClubSchedule
from core.schemas import TournamentCreate
from services.tournament import TournamentService
from services.feature_flags import FeatureFlags, FeatureFlagService

MONDAY = datetime(2026, 7, 13, 19, 25, tzinfo=ZoneInfo("Europe/Moscow"))  # понедельник
TUESDAY = datetime(2026, 7, 14, 19, 25, tzinfo=ZoneInfo("Europe/Moscow"))


def _bot():
    bot = AsyncMock()
    bot.get_me.return_value = MagicMock(username="TestBot")
    bot.send_message.return_value = MagicMock(message_id=123)
    return bot


class TestSendRegistrationOpen:
    async def test_button_is_a_deck_deeplink(self, db, monkeypatch):
        FeatureFlagService(db).toggle(FeatureFlags.LIVE_REGISTRATION_COUNT)
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", 777)
        club = Club(name="Edinorog", chat_id=-100, schedules=[])
        bot = _bot()
        tournament = TournamentService(db).create_tournament(TournamentCreate(title="Pauper", chat_id=-100))

        await send_registration_open(bot, db, club, tournament_id=tournament.id, base_text="Регистрация открыта")

        # ушло и в чат клуба, и владельцу
        chats = {c.kwargs["chat_id"] for c in bot.send_message.call_args_list}
        assert chats == {-100, 777}
        button = bot.send_message.call_args_list[0].kwargs["reply_markup"].inline_keyboard[0][0]
        assert button.url == f"https://t.me/TestBot?start=deck_{tournament.id}"
        assert all("Записалось: 0" in c.kwargs["text"] for c in bot.send_message.call_args_list)
        assert db.query(models.TournamentRegistrationMessage).count() == 2

    async def test_disabled_flag_sends_plain_message_without_tracking(self, db, monkeypatch):
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", 777)
        club = Club(name="Edinorog", chat_id=-100, schedules=[])
        bot = _bot()
        tournament = TournamentService(db).create_tournament(TournamentCreate(title="Pauper", chat_id=-100))

        await send_registration_open(bot, db, club, tournament_id=tournament.id, base_text="Регистрация открыта")

        assert all(c.kwargs["text"] == "Регистрация открыта" for c in bot.send_message.call_args_list)
        assert db.query(models.TournamentRegistrationMessage).count() == 0

    async def test_skips_missing_chat_ids(self, db, monkeypatch):
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", None)
        club = Club(name="Edinorog", chat_id=0, schedules=[])  # нет ни группы, ни владельца
        bot = _bot()

        await send_registration_open(bot, db, club, tournament_id=1, base_text="x")

        bot.send_message.assert_not_awaited()
        bot.get_me.assert_not_awaited()  # без адресатов даже get_me не зовём

    async def test_get_me_failure_still_sends_without_button(self, db, monkeypatch):
        """Сбой get_me не должен глушить анонс: шлём текст без кнопки-диплинка."""
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", 777)
        club = Club(name="Edinorog", chat_id=-100, schedules=[])
        bot = _bot()
        bot.get_me.side_effect = TelegramError("boom")
        tournament = TournamentService(db).create_tournament(TournamentCreate(title="Pauper", chat_id=-100))

        await send_registration_open(bot, db, club, tournament_id=tournament.id, base_text="Регистрация открыта")

        assert bot.send_message.await_count == 2
        assert all(c.kwargs.get("reply_markup") is None for c in bot.send_message.call_args_list)


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
        assert times[("Goldfish", "friday")] == "19:45"
        assert times[("Edinorog", "monday")] == "19:25"
        assert times[("Edinorog", "thursday")] == "19:25"
        # Четверг у Goldfish отключён — остались только пятницы
        assert ("Goldfish", "thursday") not in times
