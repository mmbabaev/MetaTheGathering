"""Tests for AetherHub club page parsing and scheduler job logic."""

import asyncio
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from bot.scheduler import AetherhubImportJob, CreateTournamentJob
from core.config import Club, ClubSchedule
from core.models import TournamentStatus
from core.schemas import TournamentCreate
from services.aetherhub_import_service import AetherhubImportService
from services.aetherhub_models import ClubTournamentLink
from services.aetherhub_service import PAUPER_RE, AetherhubService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _club_page_html(entries: list[dict]) -> str:
    """Build a minimal AetherHub-like club page HTML from a list of {name, url, date_str}."""
    rows = ""
    for e in entries:
        rows += f'<tr><td><a href="{e["url"]}">{e["name"]}</a></td><td>{e.get("date_str", "")}</td></tr>\n'
    return f"<html><body><table>{rows}</table></body></html>"


TODAY = date(2026, 4, 24)
TOURNEY_URL = "https://aetherhub.com/Tourney/RoundTourney/12345"

TZ = ZoneInfo("Europe/Moscow")
# April 24, 2026 = Friday (weekday=4)
FRIDAY_NOW = datetime(2026, 4, 24, 21, 0, tzinfo=TZ)
FRIDAY_DATE = date(2026, 4, 24)


# ---------------------------------------------------------------------------
# _extract_date
# ---------------------------------------------------------------------------


class TestExtractDate:
    svc = AetherhubService()

    def test_iso_format(self):
        assert self.svc._extract_date("Goldfish Pauper 2026-04-24") == date(2026, 4, 24)

    def test_dot_format(self):
        assert self.svc._extract_date("Goldfish Pauper 24.04.2026") == date(2026, 4, 24)

    def test_slash_format(self):
        assert self.svc._extract_date("Pauper 4/24/2026") == date(2026, 4, 24)

    def test_month_name_format(self):
        assert self.svc._extract_date("Apr 24, 2026") == date(2026, 4, 24)

    def test_month_name_no_comma(self):
        assert self.svc._extract_date("April 24 2026") == date(2026, 4, 24)

    def test_no_date_returns_none(self):
        assert self.svc._extract_date("Goldfish Pauper Spring Series") is None

    def test_date_in_cell_next_to_name(self):
        assert self.svc._extract_date("Tournament Name 2026-04-24 some extra text") == date(2026, 4, 24)


# ---------------------------------------------------------------------------
# PAUPER_RE
# ---------------------------------------------------------------------------


class TestPauperPattern:
    @pytest.mark.parametrize(
        "name",
        [
            "Goldfish Pauper 2026-04-24",
            "PAUPER Thursday",
            "pauper league",
            "Goldfish пупер",
            "ПУПЕР ЛИГА",
            "Edinorog Pauper Monthly",
        ],
    )
    def test_matches(self, name):
        assert PAUPER_RE.search(name)

    @pytest.mark.parametrize(
        "name",
        [
            "Goldfish Modern League",
            "Standard Open",
            "Legacy Cup",
        ],
    )
    def test_no_match(self, name):
        assert not PAUPER_RE.search(name)


# ---------------------------------------------------------------------------
# _parse_club_page
# ---------------------------------------------------------------------------


class TestParseClubPage:
    svc = AetherhubService()

    def test_returns_links(self):
        html = _club_page_html(
            [
                {"name": "Goldfish Pauper 2026-04-24", "url": "/Tourney/RoundTourney/1", "date_str": "2026-04-24"},
            ]
        )
        links = self.svc._parse_club_page(html)
        assert len(links) == 1
        assert links[0].name == "Goldfish Pauper 2026-04-24"
        assert links[0].url == "https://aetherhub.com/Tourney/RoundTourney/1"

    def test_extracts_date_from_name(self):
        html = _club_page_html(
            [
                {"name": "Pauper 2026-04-24", "url": "/Tourney/RoundTourney/1"},
            ]
        )
        links = self.svc._parse_club_page(html)
        assert links[0].date == date(2026, 4, 24)

    def test_extracts_date_from_row_context(self):
        html = (
            "<html><body><table>"
            '<tr><td><a href="/Tourney/RoundTourney/1">Pauper</a></td>'
            "<td>2026-04-24</td></tr>"
            "</table></body></html>"
        )
        links = self.svc._parse_club_page(html)
        assert links[0].date == date(2026, 4, 24)

    def test_deduplicates_same_url(self):
        html = (
            "<html><body>"
            '<a href="/Tourney/RoundTourney/1">Pauper 2026-04-24</a>'
            '<a href="/Tourney/RoundTourney/1">Pauper 2026-04-24</a>'
            "</body></html>"
        )
        links = self.svc._parse_club_page(html)
        assert len(links) == 1

    def test_ignores_non_tourney_links(self):
        html = (
            "<html><body>"
            '<a href="/User/GoldFish">Profile</a>'
            '<a href="/Deck/View/123">Deck</a>'
            '<a href="/Tourney/RoundTourney/1">Pauper 2026-04-24</a>'
            "</body></html>"
        )
        links = self.svc._parse_club_page(html)
        assert len(links) == 1

    def test_absolute_urls_preserved(self):
        html = f'<html><body><a href="{TOURNEY_URL}">Pauper 2026-04-24</a></body></html>'
        links = self.svc._parse_club_page(html)
        assert links[0].url == TOURNEY_URL

    def test_relative_urls_made_absolute(self):
        html = '<html><body><a href="/Tourney/RoundTourney/1">Pauper 2026-04-24</a></body></html>'
        links = self.svc._parse_club_page(html)
        assert links[0].url.startswith("https://aetherhub.com")

    def test_empty_page_returns_empty_list(self):
        assert self.svc._parse_club_page("<html><body></body></html>") == []

    def test_multiple_tournaments(self):
        html = _club_page_html(
            [
                {"name": "Pauper 2026-04-24", "url": "/Tourney/RoundTourney/1"},
                {"name": "Pauper 2026-04-17", "url": "/Tourney/RoundTourney/2"},
                {"name": "Pauper 2026-04-10", "url": "/Tourney/RoundTourney/3"},
            ]
        )
        links = self.svc._parse_club_page(html)
        assert len(links) == 3

    def test_none_date_when_not_parseable(self):
        html = _club_page_html(
            [
                {"name": "Pauper Spring Series", "url": "/Tourney/RoundTourney/1"},
            ]
        )
        links = self.svc._parse_club_page(html)
        assert links[0].date is None


# ---------------------------------------------------------------------------
# find_todays_pauper_tournament
# ---------------------------------------------------------------------------


class TestFindTodaysPauperTournament:
    def _make_html(self, name: str, date_str: str, url: str = "/Tourney/RoundTourney/1") -> str:
        return _club_page_html([{"name": name, "url": url, "date_str": date_str}])

    def _svc(self, html: str) -> AetherhubService:
        mock = MagicMock()
        mock.get.return_value.text = html
        return AetherhubService(scraper=mock)

    def test_finds_todays_pauper(self):
        svc = self._svc(self._make_html("Goldfish Pauper 2026-04-24", "2026-04-24"))
        result = svc.find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=TODAY)
        assert result == "https://aetherhub.com/Tourney/RoundTourney/1"

    def test_wrong_date_returns_none(self):
        svc = self._svc(self._make_html("Goldfish Pauper 2026-04-17", "2026-04-17"))
        result = svc.find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=TODAY)
        assert result is None

    def test_non_pauper_name_returns_none(self):
        svc = self._svc(self._make_html("Goldfish Modern 2026-04-24", "2026-04-24"))
        result = svc.find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=TODAY)
        assert result is None

    @pytest.mark.parametrize(
        "name",
        [
            "Goldfish Pauper 2026-04-24",
            "Goldfish PAUPER 2026-04-24",
            "Goldfish pauper 2026-04-24",
            "Goldfish пупер 2026-04-24",
            "Goldfish ПУПЕР 2026-04-24",
        ],
    )
    def test_case_insensitive_pauper_match(self, name):
        svc = self._svc(self._make_html(name, "2026-04-24"))
        result = svc.find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=TODAY)
        assert result is not None

    def test_returns_first_matching_url(self):
        html = _club_page_html(
            [
                {"name": "Pauper 2026-04-24", "url": "/Tourney/RoundTourney/111"},
                {"name": "Pauper 2026-04-24 Extra", "url": "/Tourney/RoundTourney/222"},
            ]
        )
        result = self._svc(html).find_todays_pauper_tournament("https://aetherhub.com/User/Test", today=TODAY)
        assert result == "https://aetherhub.com/Tourney/RoundTourney/111"

    def test_empty_page_returns_none(self):
        svc = self._svc("<html></html>")
        result = svc.find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=TODAY)
        assert result is None

    def test_find_latest_ignores_date(self):
        """today=None returns first pauper regardless of date."""
        html = _club_page_html(
            [
                {"name": "Pauper 2026-03-01", "url": "/Tourney/RoundTourney/OLD", "date_str": "2026-03-01"},
            ]
        )
        svc = self._svc(html)
        result = svc.find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=None)
        assert result == "https://aetherhub.com/Tourney/RoundTourney/OLD"

    def test_find_latest_skips_non_pauper(self):
        """today=None still filters by pauper name."""
        html = _club_page_html(
            [
                {"name": "Modern League 2026-03-01", "url": "/Tourney/RoundTourney/1", "date_str": "2026-03-01"},
            ]
        )
        svc = self._svc(html)
        result = svc.find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=None)
        assert result is None


# ---------------------------------------------------------------------------
# AetherhubImportJob
# ---------------------------------------------------------------------------


def _make_import_job(
    weekday="friday",
    aetherhub_url="https://aetherhub.com/User/GoldFish",
    fetch_times=None,
    find_latest=False,
    aetherhub_service=None,
) -> AetherhubImportJob:
    club = Club(name="Goldfish", chat_id=0, aetherhub_url=aetherhub_url, schedules=[])
    schedule = ClubSchedule(
        weekday=weekday,
        game_time="19:30",
        aetherhub_fetch_times=fetch_times or ["21:00"],
        find_latest=find_latest,
    )
    return AetherhubImportJob(club, schedule, aetherhub_service=aetherhub_service)


class TestAetherhubImportJob:
    """Tests for AetherhubImportJob — db and now are injected directly."""

    def test_skips_when_no_aetherhub_url_configured(self, db):
        mock_svc = MagicMock()
        job = _make_import_job(aetherhub_url=None, aetherhub_service=mock_svc)
        asyncio.run(job.run(now=FRIDAY_NOW, db=db))
        mock_svc.find_todays_pauper_tournament.assert_not_called()

    def test_skips_when_no_active_tournament(self, db):
        mock_svc = MagicMock()
        job = _make_import_job(aetherhub_service=mock_svc)
        asyncio.run(job.run(now=FRIDAY_NOW, db=db))
        mock_svc.find_todays_pauper_tournament.assert_not_called()

    def test_fetches_club_page_when_no_url_on_tournament(self, db, svc):
        """When tournament has no aetherhub_url, fetch the club page to find it."""
        found_url = "https://aetherhub.com/Tourney/RoundTourney/99"
        mock_svc = MagicMock()
        mock_svc.find_todays_pauper_tournament.return_value = found_url
        mock_svc.fetch_tournament.return_value = MagicMock()

        svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        job = _make_import_job(aetherhub_service=mock_svc)

        with (
            patch("bot.scheduler.AetherhubImportService") as mock_import_cls,
            patch("bot.scheduler.SessionLocal", return_value=MagicMock()),
        ):
            mock_import_cls.return_value.import_tournament.return_value = MagicMock(
                registered=5, already_registered=0, pairings_saved=20
            )
            asyncio.run(job.run(now=FRIDAY_NOW, db=db))

        mock_svc.find_todays_pauper_tournament.assert_called_once_with(job.club.aetherhub_url, today=FRIDAY_DATE)
        mock_svc.fetch_tournament.assert_called_once_with(found_url)
        mock_import_cls.return_value.import_tournament.assert_called_once()

    def test_uses_stored_url_without_fetching_club_page(self, db, svc):
        """When tournament already has aetherhub_url stored, skip club page fetch."""
        stored_url = "https://aetherhub.com/Tourney/RoundTourney/42"
        mock_svc = MagicMock()
        mock_svc.fetch_tournament.return_value = MagicMock()

        t = svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        svc.set_aetherhub_url(t.id, stored_url)
        job = _make_import_job(aetherhub_service=mock_svc)

        with (
            patch("bot.scheduler.AetherhubImportService") as mock_import_cls,
            patch("bot.scheduler.SessionLocal", return_value=MagicMock()),
        ):
            mock_import_cls.return_value.import_tournament.return_value = MagicMock(
                registered=0, already_registered=5, pairings_saved=10
            )
            asyncio.run(job.run(now=FRIDAY_NOW, db=db))

        mock_svc.find_todays_pauper_tournament.assert_not_called()
        mock_svc.fetch_tournament.assert_called_once_with(stored_url)

    def test_stops_gracefully_when_club_page_has_no_tournament(self, db, svc):
        """If find_todays_pauper_tournament returns None, import is skipped."""
        mock_svc = MagicMock()
        mock_svc.find_todays_pauper_tournament.return_value = None

        svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        job = _make_import_job(aetherhub_service=mock_svc)
        asyncio.run(job.run(now=FRIDAY_NOW, db=db))

        mock_svc.fetch_tournament.assert_not_called()

    def test_saves_url_after_successful_import(self, db, svc):
        """After import, aetherhub_url is saved via a separate session."""
        found_url = "https://aetherhub.com/Tourney/RoundTourney/77"
        mock_svc = MagicMock()
        mock_svc.find_todays_pauper_tournament.return_value = found_url
        mock_svc.fetch_tournament.return_value = MagicMock()

        t = svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        job = _make_import_job(aetherhub_service=mock_svc)

        db2_mock = MagicMock()
        with (
            patch("bot.scheduler.AetherhubImportService") as mock_import_cls,
            patch("bot.scheduler.TournamentService") as mock_ts_cls,
            patch("bot.scheduler.SessionLocal", return_value=db2_mock),
        ):
            mock_import_cls.return_value.import_tournament.return_value = MagicMock(
                registered=3, already_registered=0, pairings_saved=6
            )
            asyncio.run(job.run(now=FRIDAY_NOW, db=db))

        mock_ts_cls.assert_called_once_with(db2_mock)
        mock_ts_cls.return_value.set_aetherhub_url.assert_called_once_with(t.id, found_url)

    def test_club_page_fetch_exception_is_handled(self, db, svc):
        """If fetching the club page raises, import is skipped gracefully."""
        mock_svc = MagicMock()
        mock_svc.find_todays_pauper_tournament.side_effect = Exception("timeout")

        svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        job = _make_import_job(aetherhub_service=mock_svc)
        asyncio.run(job.run(now=FRIDAY_NOW, db=db))

        mock_svc.fetch_tournament.assert_not_called()

    def test_fetch_tournament_exception_is_handled(self, db, svc):
        """If fetching tournament data raises, import is skipped gracefully."""
        found_url = "https://aetherhub.com/Tourney/RoundTourney/99"
        mock_svc = MagicMock()
        mock_svc.find_todays_pauper_tournament.return_value = found_url
        mock_svc.fetch_tournament.side_effect = Exception("network error")

        svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        job = _make_import_job(aetherhub_service=mock_svc)

        with patch("bot.scheduler.AetherhubImportService") as mock_import_cls:
            asyncio.run(job.run(now=FRIDAY_NOW, db=db))
            mock_import_cls.return_value.import_tournament.assert_not_called()

    def test_find_latest_passes_today_none(self, db, svc):
        """When find_latest=True, find_todays_pauper_tournament is called with today=None."""
        mock_svc = MagicMock()
        mock_svc.find_todays_pauper_tournament.return_value = None
        job = _make_import_job(find_latest=True, aetherhub_service=mock_svc)
        svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        asyncio.run(job.run(now=FRIDAY_NOW, db=db))
        mock_svc.find_todays_pauper_tournament.assert_called_once()
        _, kwargs = mock_svc.find_todays_pauper_tournament.call_args
        assert kwargs.get("today") is None

    def test_find_today_passes_date(self, db, svc):
        """When find_latest=False, find_todays_pauper_tournament is called with today=now.date()."""
        mock_svc = MagicMock()
        mock_svc.find_todays_pauper_tournament.return_value = None
        job = _make_import_job(find_latest=False, aetherhub_service=mock_svc)
        svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        asyncio.run(job.run(now=FRIDAY_NOW, db=db))
        mock_svc.find_todays_pauper_tournament.assert_called_once()
        _, kwargs = mock_svc.find_todays_pauper_tournament.call_args
        assert kwargs.get("today") == FRIDAY_NOW.date()


# ---------------------------------------------------------------------------
# AetherhubImportJob find_latest — end-to-end
# ---------------------------------------------------------------------------


class TestAetherhubImportJobFindLatest:
    """Full-path tests: find_latest=True runs import with first pauper on page."""

    def test_find_latest_imports_old_tournament(self, db, svc):
        """find_latest=True fetches and imports even when tournament date is in the past."""
        old_url = "https://aetherhub.com/Tourney/RoundTourney/999"
        mock_svc = MagicMock()
        mock_svc.find_todays_pauper_tournament.return_value = old_url
        mock_svc.fetch_tournament.return_value = MagicMock()

        svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        job = _make_import_job(find_latest=True, aetherhub_service=mock_svc)

        with (
            patch("bot.scheduler.AetherhubImportService") as mock_import_cls,
            patch("bot.scheduler.SessionLocal", return_value=MagicMock()),
        ):
            mock_import_cls.return_value.import_tournament.return_value = MagicMock(
                registered=2, already_registered=0, pairings_saved=4
            )
            asyncio.run(job.run(now=FRIDAY_NOW, db=db))
            mock_import_cls.return_value.import_tournament.assert_called_once()

    def test_find_latest_no_pauper_on_page_skips_import(self, db, svc):
        """find_latest=True + no pauper on page → import is skipped."""
        mock_svc = MagicMock()
        mock_svc.find_todays_pauper_tournament.return_value = None

        svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        job = _make_import_job(find_latest=True, aetherhub_service=mock_svc)
        asyncio.run(job.run(now=FRIDAY_NOW, db=db))
        mock_svc.fetch_tournament.assert_not_called()

    def test_find_latest_multiple_paupers_returns_first(self):
        """today=None returns the first pauper in page order, regardless of date."""
        html = _club_page_html(
            [
                {"name": "Pauper 2026-04-17", "url": "/Tourney/RoundTourney/100", "date_str": "2026-04-17"},
                {"name": "Pauper 2026-04-10", "url": "/Tourney/RoundTourney/99", "date_str": "2026-04-10"},
            ]
        )
        scraper = MagicMock()
        scraper.get.return_value.text = html
        service = AetherhubService(scraper=scraper)
        result = service.find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=None)
        assert result == "https://aetherhub.com/Tourney/RoundTourney/100"


# ---------------------------------------------------------------------------
# Debug club configuration
# ---------------------------------------------------------------------------


class TestDebugClubConfig:
    """Verify debug club has correct find_latest and fetch times."""

    def test_debug_club_has_find_latest(self):
        from unittest.mock import patch as _patch

        with _patch("bot.scheduler.settings") as mock_settings:
            mock_settings.DEBUG = True
            from bot.scheduler import get_clubs

            clubs = get_clubs()

        debug_clubs = [c for c in clubs if c.name == "Debug"]
        assert debug_clubs, "Debug club should exist when DEBUG=True"
        debug = debug_clubs[0]
        assert any(s.find_latest for s in debug.schedules)

    def test_debug_club_fetch_times(self):
        from unittest.mock import patch as _patch

        with _patch("bot.scheduler.settings") as mock_settings:
            mock_settings.DEBUG = True
            from bot.scheduler import get_clubs

            clubs = get_clubs()

        debug = next(c for c in clubs if c.name == "Debug")
        all_times = [t for s in debug.schedules for t in s.aetherhub_fetch_times]
        assert "12:31" in all_times

    def test_debug_club_has_aetherhub_url(self):
        from unittest.mock import patch as _patch

        with _patch("bot.scheduler.settings") as mock_settings:
            mock_settings.DEBUG = True
            from bot.scheduler import get_clubs

            clubs = get_clubs()

        debug = next(c for c in clubs if c.name == "Debug")
        assert debug.aetherhub_url is not None


# ---------------------------------------------------------------------------
# CreateTournamentJob
# ---------------------------------------------------------------------------


def _make_create_job(weekday="friday", chat_id=100) -> CreateTournamentJob:
    club = Club(name="Goldfish", chat_id=chat_id, aetherhub_url=None, schedules=[])
    schedule = ClubSchedule(weekday=weekday, game_time="19:30")
    return CreateTournamentJob(club, schedule)


class TestCreateTournamentJob:
    """Tests for CreateTournamentJob — db and now are injected directly."""

    def test_creates_tournament_on_correct_weekday(self, db, svc):
        job = _make_create_job(weekday="friday", chat_id=0)
        bot = AsyncMock()
        asyncio.run(job.run(bot=bot, now=FRIDAY_NOW, db=db))
        t = svc.get_active_tournament_for_chat(0)
        assert t is not None
        assert "Goldfish" in t.title
        assert FRIDAY_DATE.strftime("%d.%m.%Y") in t.title

    def test_closes_previous_active_tournament(self, db, svc):
        job = _make_create_job(weekday="friday", chat_id=0)
        old = svc.create_tournament(TournamentCreate(title="Old", chat_id=0, slug="old", club="Goldfish"))
        bot = AsyncMock()
        asyncio.run(job.run(bot=bot, now=FRIDAY_NOW, db=db))
        from sqlalchemy import select

        import core.models as m

        old_refreshed = db.get(m.Tournament, old.id)
        assert old_refreshed.status == TournamentStatus.CLOSED

    def test_sends_message_to_announce_chat_id(self, db):
        job = _make_create_job(weekday="friday", chat_id=42)
        bot = AsyncMock()
        with patch("bot.scheduler.settings") as mock_settings:
            mock_settings.ANNOUNCE_CHAT_ID = 999
            asyncio.run(job.run(bot=bot, now=FRIDAY_NOW, db=db))
        bot.send_message.assert_called_once()
        call_kwargs = bot.send_message.call_args
        assert call_kwargs.kwargs.get("chat_id") == 999 or call_kwargs.args[0] == 999

    def test_no_message_when_announce_chat_id_not_set(self, db):
        job = _make_create_job(weekday="friday", chat_id=42)
        bot = AsyncMock()
        with patch("bot.scheduler.settings") as mock_settings:
            mock_settings.ANNOUNCE_CHAT_ID = None
            asyncio.run(job.run(bot=bot, now=FRIDAY_NOW, db=db))
        bot.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# AetherhubImportJob weekday guard
# ---------------------------------------------------------------------------

# Saturday — weekday=5
SATURDAY_NOW = datetime(2026, 4, 25, 21, 0, tzinfo=TZ)


class TestAetherhubImportJobWeekdayGuard:
    def test_skips_on_wrong_weekday(self, db, svc):
        """AetherhubImportJob must not run when now.weekday() != schedule weekday."""
        mock_svc = MagicMock()
        job = _make_import_job(weekday="friday", aetherhub_service=mock_svc)
        svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        asyncio.run(job.run(now=SATURDAY_NOW, db=db))
        mock_svc.find_todays_pauper_tournament.assert_not_called()

    def test_runs_on_correct_weekday(self, db, svc):
        """AetherhubImportJob runs when weekday matches."""
        mock_svc = MagicMock()
        mock_svc.find_todays_pauper_tournament.return_value = None
        job = _make_import_job(weekday="friday", aetherhub_service=mock_svc)
        svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        asyncio.run(job.run(now=FRIDAY_NOW, db=db))
        mock_svc.find_todays_pauper_tournament.assert_called_once()


# ---------------------------------------------------------------------------
# format_schedule_text decomposition
# ---------------------------------------------------------------------------


class TestFormatScheduleText:
    def test_contains_club_name(self):
        from bot.scheduler import _format_club_schedule, format_schedule_text

        text = format_schedule_text()
        assert "Goldfish" in text
        assert "Edinorog" in text

    def test_format_club_schedule_contains_weekday_and_times(self):
        from bot.scheduler import _format_club_schedule

        club = Club(
            name="TestClub",
            chat_id=0,
            schedules=[
                ClubSchedule(
                    weekday="friday", game_time="19:30", create_time="12:00", aetherhub_fetch_times=["20:00", "21:00"]
                )
            ],
        )
        text = _format_club_schedule(club)
        assert "пятница" in text
        assert "19:30" in text
        assert "12:00" in text
        assert "20:00" in text

    def test_format_club_schedule_no_import_times(self):
        from bot.scheduler import _format_club_schedule

        club = Club(
            name="TestClub",
            chat_id=0,
            schedules=[ClubSchedule(weekday="monday", game_time="18:00")],
        )
        text = _format_club_schedule(club)
        assert "импорт" not in text
