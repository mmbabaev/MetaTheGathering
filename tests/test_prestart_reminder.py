"""Tests for the pre-start deck reminder + registration-open deeplink message."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from telegram.error import TelegramError

from bot.scheduler import PreStartReminderJob, get_clubs, send_registration_open
from core import models
from core.config import Club, ClubSchedule
from core.schemas import TournamentCreate
from services.deck_reminders import DeckReminderStage
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.tournament import TournamentService

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

    async def test_disabled_flag_sends_plain_message_and_tracks_it_for_future_enable(self, db, monkeypatch):
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", 777)
        club = Club(name="Edinorog", chat_id=-100, schedules=[])
        bot = _bot()
        tournament = TournamentService(db).create_tournament(TournamentCreate(title="Pauper", chat_id=-100))

        await send_registration_open(bot, db, club, tournament_id=tournament.id, base_text="Регистрация открыта")

        assert all(c.kwargs["text"] == "Регистрация открыта" for c in bot.send_message.call_args_list)
        rows = db.query(models.TournamentRegistrationMessage).all()
        assert len(rows) == 2
        assert all(row.rendered_participant_count == -1 for row in rows)

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

    async def test_konetskhod_announcement_sent_as_photo_with_caption(self, db, tmp_path, monkeypatch):
        """Анонс Концехода с иконкой уходит фото: текст в caption, кнопка при фото."""
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", None)
        icon = tmp_path / "konetskhod.png"
        icon.write_bytes(b"not-a-real-png")
        monkeypatch.setattr("bot.registration_messages.settings.KONETSKHOD_ICON_PATH", str(icon))
        club = Club(name="Endstep-ru", chat_id=-100, schedules=[], title_prefix="⏭️🦶 ", is_online=True)
        bot = _bot()
        bot.send_photo.return_value = MagicMock(message_id=555)
        tournament = TournamentService(db).create_tournament(
            TournamentCreate(title="⏭️🦶 Концеход Pauper #1", chat_id=-100, club="Endstep-ru")
        )

        await send_registration_open(bot, db, club, tournament_id=tournament.id, base_text="Регистрация открыта")

        bot.send_photo.assert_awaited_once()
        kwargs = bot.send_photo.await_args.kwargs
        assert kwargs["chat_id"] == -100
        assert kwargs["caption"] == "Регистрация открыта"
        assert kwargs["reply_markup"] is not None
        bot.send_message.assert_not_awaited()
        row = db.query(models.TournamentRegistrationMessage).one()
        assert row.message_id == 555

    async def test_konetskhod_photo_skipped_when_icon_file_missing(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", None)
        monkeypatch.setattr("bot.registration_messages.settings.KONETSKHOD_ICON_PATH", str(tmp_path / "missing.png"))
        club = Club(name="Endstep-ru", chat_id=-100, schedules=[], title_prefix="⏭️🦶 ", is_online=True)
        bot = _bot()
        tournament = TournamentService(db).create_tournament(
            TournamentCreate(title="⏭️🦶 Концеход Pauper #1", chat_id=-100, club="Endstep-ru")
        )

        await send_registration_open(bot, db, club, tournament_id=tournament.id, base_text="Регистрация открыта")

        bot.send_photo.assert_not_awaited()
        bot.send_message.assert_awaited_once()

    async def test_draft_and_other_clubs_never_send_photo(self, db, tmp_path, monkeypatch):
        icon = tmp_path / "konetskhod.png"
        icon.write_bytes(b"not-a-real-png")
        monkeypatch.setattr("bot.registration_messages.settings.KONETSKHOD_ICON_PATH", str(icon))
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", None)
        club = Club(name="Endstep draft", chat_id=-100, schedules=[], title_prefix="⏭️🦶 ", is_online=True)
        bot = _bot()
        tournament = TournamentService(db).create_tournament(
            TournamentCreate(title="⏭️🦶 Endstep draft 05.09.2026", chat_id=-100, club="Endstep draft", is_draft=True)
        )

        await send_registration_open(bot, db, club, tournament_id=tournament.id, base_text="Регистрация открыта")

        bot.send_photo.assert_not_awaited()
        bot.send_message.assert_awaited_once()


class TestPreStartReminderJob:
    def _club_schedule(self):
        club = Club(name="Edinorog", chat_id=-100, schedules=[])
        schedule = ClubSchedule(weekday="monday", game_time="19:30", reminder_time="19:25")
        return club, schedule

    async def test_reminds_when_active_tournament_exists(self, db, monkeypatch):
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", 777)
        club, schedule = self._club_schedule()
        TournamentService(db).create_tournament(TournamentCreate(title="Pauper", chat_id=-100, club=club.name))
        bot = _bot()

        await PreStartReminderJob(club, schedule).run(bot=bot, now=MONDAY, db=db)

        bot.send_message.assert_awaited()
        assert "начинается" in bot.send_message.call_args_list[0].kwargs["text"]

    async def test_reminder_includes_club_title_prefix(self, db, monkeypatch):
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", None)
        club = Club(name="Endstep-ru", chat_id=-100, schedules=[], title_prefix="⏭️🦶 ", is_online=True)
        schedule = ClubSchedule(weekday="monday", game_time="20:00", reminder_time="19:25")
        TournamentService(db).create_tournament(
            TournamentCreate(title="⏭️🦶 Концеход Pauper #3", chat_id=-100, club=club.name)
        )
        bot = _bot()

        await PreStartReminderJob(club, schedule).run(bot=bot, now=MONDAY, db=db)

        assert bot.send_message.await_args.kwargs["text"].startswith("⏰ ⏭️🦶 Концеход Pauper #3")

    async def test_dms_deferred_players_after_group_reminder(self, db, monkeypatch):
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", None)
        reminder = AsyncMock()
        monkeypatch.setattr("bot.scheduler.send_deferred_deck_reminders", reminder)
        club, schedule = self._club_schedule()
        tournament = TournamentService(db).create_tournament(
            TournamentCreate(title="Pauper", chat_id=-100, club=club.name)
        )
        bot = _bot()

        await PreStartReminderJob(club, schedule).run(bot=bot, now=MONDAY, db=db)

        reminder.assert_awaited_once_with(
            bot,
            db,
            tournament.id,
            DeckReminderStage.PRESTART,
        )

    async def test_group_failure_does_not_skip_deferred_player_dms(self, db, monkeypatch):
        monkeypatch.setattr("bot.scheduler.settings.OWNER_CHAT_ID", None)
        monkeypatch.setattr(
            "bot.scheduler.send_registration_open",
            AsyncMock(side_effect=TelegramError("group unavailable")),
        )
        reminder = AsyncMock()
        monkeypatch.setattr("bot.scheduler.send_deferred_deck_reminders", reminder)
        club, schedule = self._club_schedule()
        tournament = TournamentService(db).create_tournament(
            TournamentCreate(title="Pauper", chat_id=-100, club=club.name)
        )
        bot = _bot()

        await PreStartReminderJob(club, schedule).run(bot=bot, now=MONDAY, db=db)

        reminder.assert_awaited_once_with(
            bot,
            db,
            tournament.id,
            DeckReminderStage.PRESTART,
        )

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
        assert times[("Pair of dice", "tuesday")] == "19:25"
        assert times[("Pair of dice", "sunday")] == "13:25"
        assert times[("Калининград", "saturday")] == "16:55"
        # Четверг у Goldfish отключён — остались только пятницы
        assert ("Goldfish", "thursday") not in times
