"""Tests for AetherHub club page parsing and auto-import scheduler logic."""

import pytest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from core.config import ClubConfig
from core.schemas import TournamentCreate
from core.models import TournamentStatus
from services.aetherhub import (
    _parse_club_page,
    _extract_date,
    find_todays_pauper_tournament,
    ClubTournamentLink,
    PAUPER_RE,
)
from services.aetherhub_import import AetherhubImportService


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


# ---------------------------------------------------------------------------
# _extract_date
# ---------------------------------------------------------------------------

class TestExtractDate:
    def test_iso_format(self):
        assert _extract_date("Goldfish Pauper 2026-04-24") == date(2026, 4, 24)

    def test_dot_format(self):
        assert _extract_date("Goldfish Pauper 24.04.2026") == date(2026, 4, 24)

    def test_slash_format(self):
        assert _extract_date("Pauper 4/24/2026") == date(2026, 4, 24)

    def test_month_name_format(self):
        assert _extract_date("Apr 24, 2026") == date(2026, 4, 24)

    def test_month_name_no_comma(self):
        assert _extract_date("April 24 2026") == date(2026, 4, 24)

    def test_no_date_returns_none(self):
        assert _extract_date("Goldfish Pauper Spring Series") is None

    def test_date_in_cell_next_to_name(self):
        assert _extract_date("Tournament Name 2026-04-24 some extra text") == date(2026, 4, 24)


# ---------------------------------------------------------------------------
# PAUPER_RE
# ---------------------------------------------------------------------------

class TestPauperPattern:
    @pytest.mark.parametrize("name", [
        "Goldfish Pauper 2026-04-24",
        "PAUPER Thursday",
        "pauper league",
        "Goldfish пупер",
        "ПУПЕР ЛИГА",
        "Edinorog Pauper Monthly",
    ])
    def test_matches(self, name):
        assert PAUPER_RE.search(name)

    @pytest.mark.parametrize("name", [
        "Goldfish Modern League",
        "Standard Open",
        "Legacy Cup",
    ])
    def test_no_match(self, name):
        assert not PAUPER_RE.search(name)


# ---------------------------------------------------------------------------
# _parse_club_page
# ---------------------------------------------------------------------------

class TestParseClubPage:
    def test_returns_links(self):
        html = _club_page_html([
            {"name": "Goldfish Pauper 2026-04-24", "url": "/Tourney/RoundTourney/1", "date_str": "2026-04-24"},
        ])
        links = _parse_club_page(html)
        assert len(links) == 1
        assert links[0].name == "Goldfish Pauper 2026-04-24"
        assert links[0].url == "https://aetherhub.com/Tourney/RoundTourney/1"

    def test_extracts_date_from_name(self):
        html = _club_page_html([
            {"name": "Pauper 2026-04-24", "url": "/Tourney/RoundTourney/1"},
        ])
        links = _parse_club_page(html)
        assert links[0].date == date(2026, 4, 24)

    def test_extracts_date_from_row_context(self):
        html = (
            "<html><body><table>"
            '<tr><td><a href="/Tourney/RoundTourney/1">Pauper</a></td>'
            "<td>2026-04-24</td></tr>"
            "</table></body></html>"
        )
        links = _parse_club_page(html)
        assert links[0].date == date(2026, 4, 24)

    def test_deduplicates_same_url(self):
        html = (
            "<html><body>"
            '<a href="/Tourney/RoundTourney/1">Pauper 2026-04-24</a>'
            '<a href="/Tourney/RoundTourney/1">Pauper 2026-04-24</a>'
            "</body></html>"
        )
        links = _parse_club_page(html)
        assert len(links) == 1

    def test_ignores_non_tourney_links(self):
        html = (
            "<html><body>"
            '<a href="/User/GoldFish">Profile</a>'
            '<a href="/Deck/View/123">Deck</a>'
            '<a href="/Tourney/RoundTourney/1">Pauper 2026-04-24</a>'
            "</body></html>"
        )
        links = _parse_club_page(html)
        assert len(links) == 1

    def test_absolute_urls_preserved(self):
        html = (
            "<html><body>"
            f'<a href="{TOURNEY_URL}">Pauper 2026-04-24</a>'
            "</body></html>"
        )
        links = _parse_club_page(html)
        assert links[0].url == TOURNEY_URL

    def test_relative_urls_made_absolute(self):
        html = (
            "<html><body>"
            '<a href="/Tourney/RoundTourney/1">Pauper 2026-04-24</a>'
            "</body></html>"
        )
        links = _parse_club_page(html)
        assert links[0].url.startswith("https://aetherhub.com")

    def test_empty_page_returns_empty_list(self):
        assert _parse_club_page("<html><body></body></html>") == []

    def test_multiple_tournaments(self):
        html = _club_page_html([
            {"name": "Pauper 2026-04-24", "url": "/Tourney/RoundTourney/1"},
            {"name": "Pauper 2026-04-17", "url": "/Tourney/RoundTourney/2"},
            {"name": "Pauper 2026-04-10", "url": "/Tourney/RoundTourney/3"},
        ])
        links = _parse_club_page(html)
        assert len(links) == 3

    def test_none_date_when_not_parseable(self):
        html = _club_page_html([
            {"name": "Pauper Spring Series", "url": "/Tourney/RoundTourney/1"},
        ])
        links = _parse_club_page(html)
        assert links[0].date is None


# ---------------------------------------------------------------------------
# find_todays_pauper_tournament
# ---------------------------------------------------------------------------

class TestFindTodaysPauperTournament:
    def _make_html(self, name: str, date_str: str, url: str = "/Tourney/RoundTourney/1") -> str:
        return _club_page_html([{"name": name, "url": url, "date_str": date_str}])

    @patch("services.aetherhub._scraper")
    def test_finds_todays_pauper(self, mock_scraper):
        mock_scraper.return_value.get.return_value.text = self._make_html(
            "Goldfish Pauper 2026-04-24", "2026-04-24"
        )
        result = find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=TODAY)
        assert result == "https://aetherhub.com/Tourney/RoundTourney/1"

    @patch("services.aetherhub._scraper")
    def test_wrong_date_returns_none(self, mock_scraper):
        mock_scraper.return_value.get.return_value.text = self._make_html(
            "Goldfish Pauper 2026-04-17", "2026-04-17"
        )
        result = find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=TODAY)
        assert result is None

    @patch("services.aetherhub._scraper")
    def test_non_pauper_name_returns_none(self, mock_scraper):
        mock_scraper.return_value.get.return_value.text = self._make_html(
            "Goldfish Modern 2026-04-24", "2026-04-24"
        )
        result = find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=TODAY)
        assert result is None

    @patch("services.aetherhub._scraper")
    @pytest.mark.parametrize("name", [
        "Goldfish Pauper 2026-04-24",
        "Goldfish PAUPER 2026-04-24",
        "Goldfish pauper 2026-04-24",
        "Goldfish пупер 2026-04-24",
        "Goldfish ПУПЕР 2026-04-24",
    ])
    def test_case_insensitive_pauper_match(self, mock_scraper, name):
        mock_scraper.return_value.get.return_value.text = self._make_html(name, "2026-04-24")
        result = find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=TODAY)
        assert result is not None

    @patch("services.aetherhub._scraper")
    def test_returns_first_matching_url(self, mock_scraper):
        html = _club_page_html([
            {"name": "Pauper 2026-04-24", "url": "/Tourney/RoundTourney/111"},
            {"name": "Pauper 2026-04-24 Extra", "url": "/Tourney/RoundTourney/222"},
        ])
        mock_scraper.return_value.get.return_value.text = html
        result = find_todays_pauper_tournament("https://aetherhub.com/User/Test", today=TODAY)
        assert result == "https://aetherhub.com/Tourney/RoundTourney/111"

    @patch("services.aetherhub._scraper")
    def test_empty_page_returns_none(self, mock_scraper):
        mock_scraper.return_value.get.return_value.text = "<html></html>"
        result = find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=TODAY)
        assert result is None


# ---------------------------------------------------------------------------
# _aetherhub_auto_import scheduler logic
# ---------------------------------------------------------------------------

THURSDAY = 3  # weekday index

def _make_club(weekday="thursday", aetherhub_url="https://aetherhub.com/User/GoldFish",
               fetch_times=None) -> ClubConfig:
    return ClubConfig(
        name="Goldfish",
        weekday=weekday,
        chat_id=0,
        game_time="19:30",
        aetherhub_url=aetherhub_url,
        aetherhub_fetch_times=fetch_times or ["21:00"],
    )


class TestAetherhubAutoImport:
    """Tests for _aetherhub_auto_import scheduler function."""

    def _run(self, club, db, today_weekday=THURSDAY, today_date=TODAY,
             club_page_url=None, db2=None):
        """Run _aetherhub_auto_import with mocked time and DB."""
        from bot.scheduler import _aetherhub_auto_import
        import asyncio

        tz = ZoneInfo("Europe/Moscow")
        fake_now = datetime(2026, 4, 23, 21, 0, tzinfo=tz)  # Thursday

        with patch("bot.scheduler.SessionLocal") as mock_sl, \
             patch("bot.scheduler.datetime") as mock_dt:

            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime
            # today() comes from datetime.now().date()

            db_instance = db
            db2_instance = db2 or MagicMock()
            call_count = [0]

            def session_factory():
                call_count[0] += 1
                if call_count[0] == 1:
                    return db_instance
                return db2_instance

            mock_sl.side_effect = session_factory

            return asyncio.run(_aetherhub_auto_import(club))

    def test_skips_wrong_weekday(self, db, svc):
        club = _make_club(weekday="friday")  # today is Thursday
        t = svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))

        from bot.scheduler import _aetherhub_auto_import
        import asyncio
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Europe/Moscow")
        fake_now = datetime(2026, 4, 23, 21, 0, tzinfo=tz)  # Thursday

        with patch("bot.scheduler.SessionLocal") as mock_sl, \
             patch("bot.scheduler.datetime") as mock_dt, \
             patch("bot.scheduler.find_todays_pauper_tournament") as mock_find:

            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime
            mock_sl.return_value = db

            asyncio.run(_aetherhub_auto_import(club))
            mock_find.assert_not_called()

    def test_skips_when_no_active_tournament(self, db, svc):
        club = _make_club()

        from bot.scheduler import _aetherhub_auto_import
        import asyncio

        tz = ZoneInfo("Europe/Moscow")
        fake_now = datetime(2026, 4, 23, 21, 0, tzinfo=tz)  # Thursday

        with patch("bot.scheduler.SessionLocal") as mock_sl, \
             patch("bot.scheduler.datetime") as mock_dt, \
             patch("bot.scheduler.find_todays_pauper_tournament") as mock_find:

            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime

            db_mock = MagicMock()
            db_mock.execute.return_value.scalar_one_or_none.return_value = None
            mock_sl.return_value = db_mock

            asyncio.run(_aetherhub_auto_import(club))
            mock_find.assert_not_called()

    def test_skips_when_no_aetherhub_url_configured(self, db, svc):
        club = _make_club(aetherhub_url=None)
        t = svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))

        from bot.scheduler import _aetherhub_auto_import
        import asyncio

        with patch("bot.scheduler.find_todays_pauper_tournament") as mock_find:
            asyncio.run(_aetherhub_auto_import(club))
            mock_find.assert_not_called()

    def test_fetches_club_page_when_no_url_on_tournament(self, db, svc):
        """When tournament has no aetherhub_url, should fetch club page to find it."""
        club = _make_club()
        t = svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))

        from bot.scheduler import _aetherhub_auto_import
        import asyncio

        tz = ZoneInfo("Europe/Moscow")
        fake_now = datetime(2026, 4, 23, 21, 0, tzinfo=tz)  # Thursday (weekday=3)

        found_url = "https://aetherhub.com/Tourney/RoundTourney/99"

        with patch("bot.scheduler.SessionLocal") as mock_sl, \
             patch("bot.scheduler.datetime") as mock_dt, \
             patch("bot.scheduler.find_todays_pauper_tournament", return_value=found_url) as mock_find, \
             patch("bot.scheduler.fetch_tournament") as mock_fetch, \
             patch("bot.scheduler.AetherhubImportService") as mock_import_cls:

            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime

            db_mock = MagicMock()
            tournament_mock = MagicMock()
            tournament_mock.aetherhub_url = None
            tournament_mock.id = t.id
            db_mock.execute.return_value.scalar_one_or_none.return_value = tournament_mock
            db2_mock = MagicMock()

            call_count = [0]
            def session_factory():
                call_count[0] += 1
                return db_mock if call_count[0] == 1 else db2_mock
            mock_sl.side_effect = session_factory

            mock_fetch.return_value = MagicMock()
            mock_import_cls.return_value.import_tournament.return_value = MagicMock(
                registered=5, already_registered=0, pairings_saved=20
            )

            asyncio.run(_aetherhub_auto_import(club))

            mock_find.assert_called_once_with(club.aetherhub_url, today=fake_now.date())
            mock_fetch.assert_called_once_with(found_url)
            mock_import_cls.return_value.import_tournament.assert_called_once()

    def test_uses_stored_url_without_fetching_club_page(self, db, svc):
        """When tournament already has aetherhub_url, skip club page fetch."""
        club = _make_club()

        from bot.scheduler import _aetherhub_auto_import
        import asyncio

        tz = ZoneInfo("Europe/Moscow")
        fake_now = datetime(2026, 4, 23, 21, 0, tzinfo=tz)  # Thursday

        stored_url = "https://aetherhub.com/Tourney/RoundTourney/42"

        with patch("bot.scheduler.SessionLocal") as mock_sl, \
             patch("bot.scheduler.datetime") as mock_dt, \
             patch("bot.scheduler.find_todays_pauper_tournament") as mock_find, \
             patch("bot.scheduler.fetch_tournament") as mock_fetch, \
             patch("bot.scheduler.AetherhubImportService") as mock_import_cls:

            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime

            db_mock = MagicMock()
            tournament_mock = MagicMock()
            tournament_mock.aetherhub_url = stored_url
            tournament_mock.id = 42
            db_mock.execute.return_value.scalar_one_or_none.return_value = tournament_mock
            db2_mock = MagicMock()

            call_count = [0]
            def session_factory():
                call_count[0] += 1
                return db_mock if call_count[0] == 1 else db2_mock
            mock_sl.side_effect = session_factory

            mock_fetch.return_value = MagicMock()
            mock_import_cls.return_value.import_tournament.return_value = MagicMock(
                registered=0, already_registered=5, pairings_saved=10
            )

            asyncio.run(_aetherhub_auto_import(club))

            mock_find.assert_not_called()
            mock_fetch.assert_called_once_with(stored_url)

    def test_stops_gracefully_when_club_page_has_no_tournament(self):
        """If find_todays_pauper_tournament returns None, import is skipped."""
        club = _make_club()

        from bot.scheduler import _aetherhub_auto_import
        import asyncio

        tz = ZoneInfo("Europe/Moscow")
        fake_now = datetime(2026, 4, 23, 21, 0, tzinfo=tz)  # Thursday

        with patch("bot.scheduler.SessionLocal") as mock_sl, \
             patch("bot.scheduler.datetime") as mock_dt, \
             patch("bot.scheduler.find_todays_pauper_tournament", return_value=None), \
             patch("bot.scheduler.fetch_tournament") as mock_fetch:

            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime

            db_mock = MagicMock()
            tournament_mock = MagicMock()
            tournament_mock.aetherhub_url = None
            tournament_mock.id = 1
            db_mock.execute.return_value.scalar_one_or_none.return_value = tournament_mock
            mock_sl.return_value = db_mock

            asyncio.run(_aetherhub_auto_import(club))
            mock_fetch.assert_not_called()

    def test_saves_url_after_successful_import(self):
        """After import, aetherhub_url should be saved via set_aetherhub_url."""
        club = _make_club()

        from bot.scheduler import _aetherhub_auto_import
        import asyncio

        tz = ZoneInfo("Europe/Moscow")
        fake_now = datetime(2026, 4, 23, 21, 0, tzinfo=tz)  # Thursday
        found_url = "https://aetherhub.com/Tourney/RoundTourney/77"

        with patch("bot.scheduler.SessionLocal") as mock_sl, \
             patch("bot.scheduler.datetime") as mock_dt, \
             patch("bot.scheduler.find_todays_pauper_tournament", return_value=found_url), \
             patch("bot.scheduler.fetch_tournament", return_value=MagicMock()), \
             patch("bot.scheduler.AetherhubImportService") as mock_import_cls, \
             patch("bot.scheduler.TournamentService") as mock_ts_cls:

            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime

            db_mock = MagicMock()
            tournament_mock = MagicMock()
            tournament_mock.aetherhub_url = None
            tournament_mock.id = 77
            db_mock.execute.return_value.scalar_one_or_none.return_value = tournament_mock
            db2_mock = MagicMock()

            call_count = [0]
            def session_factory():
                call_count[0] += 1
                return db_mock if call_count[0] == 1 else db2_mock
            mock_sl.side_effect = session_factory

            mock_import_cls.return_value.import_tournament.return_value = MagicMock(
                registered=3, already_registered=0, pairings_saved=6
            )

            asyncio.run(_aetherhub_auto_import(club))

            mock_ts_cls.return_value.set_aetherhub_url.assert_called_once_with(77, found_url)
