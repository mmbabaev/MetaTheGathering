"""Tests for AetherHub club page parsing and scheduler job logic."""

import asyncio
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import core.models as cm
from bot.scheduler import (
    AetherhubImportJob,
    CreateTournamentJob,
    _format_club_schedule,
    format_schedule_text,
    get_clubs,
)
from core.config import Club, ClubSchedule
from core.models import TournamentStatus
from core.schemas import TournamentCreate
from services.aetherhub_import_service import AetherhubImportService
from services.aetherhub_models import AetherhubTournamentData, ClubTournamentLink
from services.aetherhub_service import PAUPER_RE, AetherhubService
from services.deck_reminders import DeckReminderStage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _club_page_html(entries: list[dict]) -> str:
    """Build a minimal AetherHub-like club page HTML from a list of {name, url, date_str}."""
    rows = ""
    for e in entries:
        rows += f'<tr><td><a href="{e["url"]}">{e["name"]}</a></td><td>{e.get("date_str", "")}</td></tr>\n'
    return f"<html><body><table>{rows}</table></body></html>"


def _club_cards_html(cards: list[dict]) -> str:
    """Реалистичная разметка страницы клуба AetherHub (карточки, свежие сверху).

    Каждая карточка: заголовок-имя, подзаголовок формата и «N <unit> ago» внизу.
    У Goldfish имя — дата, формат в подзаголовке «Constructed: Pauper Tourney»;
    у Edinorog формат — в имени, подзаголовок нейтральный «Constructed Tourney».
    cards: [{name, url, subtitle?, ago?}]
    """
    body = ""
    for c in cards:
        body += (
            '<div class="d-flex"><div class="w-100 pl-2">'
            f'<h5 class="card-title"><a href="{c["url"]}"><b>{c["name"]}</b></a></h5> '
            f"{c.get('subtitle', 'Constructed Tourney')} <br/>"
            f'<small class="text-muted">{c.get("ago", "")}</small>'
            "</div></div>"
        )
    return f"<html><body>{body}</body></html>"


# Подзаголовки формата, как их отдаёт AetherHub
PAUPER_SUBTITLE = "Constructed: Pauper Tourney"  # Goldfish — формат в подзаголовке
PLAIN_SUBTITLE = "Constructed Tourney"  # Edinorog — формат в имени


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

    def test_day_month_without_year(self):
        assert self.svc._extract_date("Паупер 24.04") is not None

    def test_day_month_slash_without_year(self):
        assert self.svc._extract_date("Паупер 16/07") is not None

    def test_day_month_full_format_takes_priority(self):
        # 24.04.2026 should parse as ISO date, not DD.MM
        assert self.svc._extract_date("Goldfish 24.04.2026") == date(2026, 4, 24)


class TestExtractDayMonth:
    svc = AetherhubService()

    def test_infers_current_year_when_not_future(self):
        today = date(2026, 4, 25)
        assert self.svc._extract_day_month("Паупер 24.04", today=today) == date(2026, 4, 24)

    def test_uses_previous_year_for_future_date(self):
        today = date(2026, 1, 5)
        result = self.svc._extract_day_month("Паупер 24.04", today=today)
        assert result == date(2025, 4, 24)

    def test_returns_none_without_day_month(self):
        assert self.svc._extract_day_month("Pauper Spring Series") is None

    def test_invalid_date_returns_none(self):
        assert self.svc._extract_day_month("Паупер 99.99") is None

    def test_slash_separator(self):
        """Дата через слэш («16/07») читается наравне с точкой — иначе она терялась."""
        today = date(2026, 7, 17)
        assert self.svc._extract_day_month("Паупер 16/07", today=today) == date(2026, 7, 16)

    def test_slash_one_digit_month(self):
        today = date(2026, 7, 17)
        assert self.svc._extract_day_month("Паупер 16/7", today=today) == date(2026, 7, 16)


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
            "Паупер 24.04",
            "ПАУПЕР",
            "паупер лига",
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

    def test_ignores_tourney_nav_links_without_id(self):
        """Навигация (/Tourney/, /Tourney/Leagues …) не турниры — у них нет числового id."""
        html = (
            "<html><body>"
            '<a href="/Tourney/">Browse Tournaments</a>'
            '<a href="/Tourney/Leagues">Browse Leagues</a>'
            '<a href="/Tourney/MyTourneys">My Tournaments</a>'
            '<a href="/Tourney/RoundTourney/100670">17.07</a>'
            "</body></html>"
        )
        links = self.svc._parse_club_page(html)
        assert [link.url for link in links] == ["https://aetherhub.com/Tourney/RoundTourney/100670"]

    def test_extracts_slash_date_from_name(self):
        html = _club_page_html([{"name": "Паупер 16/07", "url": "/Tourney/RoundTourney/1"}])
        links = self.svc._parse_club_page(html, today=date(2026, 7, 17))
        assert links[0].date == date(2026, 7, 16)

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

    def test_extracts_date_from_days_ago(self):
        html = (
            "<html><body>"
            '<div class="w-100">'
            '<a href="/Tourney/RoundTourney/1">Паупер</a>'
            '<small class="text-muted">1 day ago</small>'
            "</div>"
            "</body></html>"
        )
        today = date(2026, 4, 25)
        links = self.svc._parse_club_page(html, today=today)
        assert links[0].date == date(2026, 4, 24)

    def test_days_ago_fallback_when_no_date_in_name(self):
        html = (
            "<html><body>"
            '<div class="w-100">'
            '<a href="/Tourney/RoundTourney/1">Паупер</a>'
            '<small class="text-muted">3 days ago</small>'
            "</div>"
            "</body></html>"
        )
        today = date(2026, 4, 25)
        links = self.svc._parse_club_page(html, today=today)
        assert links[0].date == date(2026, 4, 22)

    def test_name_date_takes_priority_over_days_ago(self):
        html = (
            "<html><body>"
            '<div class="w-100">'
            '<a href="/Tourney/RoundTourney/1">Pauper 2026-04-24</a>'
            '<small class="text-muted">3 days ago</small>'
            "</div>"
            "</body></html>"
        )
        today = date(2026, 4, 25)
        links = self.svc._parse_club_page(html, today=today)
        assert links[0].date == date(2026, 4, 24)

    @pytest.mark.parametrize("ago", ["4 hours ago", "an hour ago", "1 hour ago", "30 minutes ago", "just now"])
    def test_created_within_a_day_is_today(self, ago):
        """Всё моложе суток (часы/минуты/just now) без даты в имени → сегодня."""
        html = _club_cards_html([{"name": "Паупер", "url": "/Tourney/RoundTourney/1", "ago": ago}])
        today = date(2026, 4, 24)
        links = self.svc._parse_club_page(html, today=today)
        assert links[0].date == today

    def test_a_day_ago_is_yesterday(self):
        html = _club_cards_html([{"name": "Паупер", "url": "/Tourney/RoundTourney/1", "ago": "a day ago"}])
        today = date(2026, 4, 24)
        links = self.svc._parse_club_page(html, today=today)
        assert links[0].date == date(2026, 4, 23)

    def test_week_ago(self):
        html = _club_cards_html([{"name": "Паупер", "url": "/Tourney/RoundTourney/1", "ago": "1 week ago"}])
        today = date(2026, 4, 24)
        links = self.svc._parse_club_page(html, today=today)
        assert links[0].date == date(2026, 4, 17)

    def test_is_pauper_from_subtitle_when_name_is_date_only(self):
        """Goldfish: имя «17.07» без слова «паупер», но подзаголовок делает турнир паупером."""
        html = _club_cards_html([{"name": "17.07", "url": "/Tourney/RoundTourney/1", "subtitle": PAUPER_SUBTITLE}])
        assert self.svc._parse_club_page(html)[0].is_pauper is True

    def test_not_pauper_when_neither_name_nor_subtitle_says_so(self):
        html = _club_cards_html(
            [{"name": "Легаси 15.07.2026", "url": "/Tourney/RoundTourney/1", "subtitle": PLAIN_SUBTITLE}]
        )
        assert self.svc._parse_club_page(html)[0].is_pauper is False

    def test_pair_of_dice_pauper_without_date_uses_relative_age(self):
        html = _club_cards_html(
            [
                {
                    "name": "Премодерн",
                    "url": "/Tourney/RoundTourney/3",
                    "subtitle": PLAIN_SUBTITLE,
                    "ago": "1 hour ago",
                },
                {
                    "name": "Паупер",
                    "url": "/Tourney/RoundTourney/2",
                    "subtitle": PLAIN_SUBTITLE,
                    "ago": "2 hours ago",
                },
                {
                    "name": "Паупер",
                    "url": "/Tourney/RoundTourney/1",
                    "subtitle": PLAIN_SUBTITLE,
                    "ago": "2 days ago",
                },
            ]
        )
        scraper = MagicMock()
        scraper.get.return_value.text = html
        service = AetherhubService(scraper=scraper)

        result = service.find_todays_pauper_tournament(
            "https://aetherhub.com/User/Andysays",
            today=date(2026, 8, 12),
        )

        assert result == "https://aetherhub.com/Tourney/RoundTourney/2"


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
                {"name": "Pauper 2026-03-01", "url": "/Tourney/RoundTourney/300", "date_str": "2026-03-01"},
            ]
        )
        svc = self._svc(html)
        result = svc.find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=None)
        assert result == "https://aetherhub.com/Tourney/RoundTourney/300"

    def test_find_latest_skips_non_pauper(self):
        """today=None: явно другой формат не берём даже как «последний»."""
        html = _club_page_html(
            [
                {"name": "Modern League 2026-03-01", "url": "/Tourney/RoundTourney/1", "date_str": "2026-03-01"},
            ]
        )
        svc = self._svc(html)
        result = svc.find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=None)
        assert result is None

    def test_find_tournament_url_uses_explicit_date_and_format(self):
        scraper = MagicMock()
        scraper.post.return_value.json.return_value = {
            "recordsFiltered": 1,
            "model": [
                {
                    "id": 100734,
                    "name": "Паупер 20.07.2026",
                    "owner": "Edinorog",
                    "date": "2026-07-20T14:00:00",
                }
            ],
        }
        result = AetherhubService(scraper=scraper).find_tournament_url(
            "https://aetherhub.com/User/Edinorog/", date(2026, 7, 20), "Pauper"
        )
        assert result == "https://aetherhub.com/Tourney/RoundTourney/100734"
        scraper.post.assert_called_once()

    def test_find_tournament_url_rejects_other_format(self):
        with pytest.raises(ValueError, match="Unsupported"):
            self._svc("<html></html>").find_tournament_url(
                "https://aetherhub.com/User/GoldFish", date(2026, 4, 24), "Modern"
            )

    def test_find_tournament_url_does_not_use_relative_age_from_profile_page(self):
        scraper = MagicMock()
        scraper.post.return_value.json.return_value = {"recordsFiltered": 0, "model": []}
        result = AetherhubService(scraper=scraper).find_tournament_url(
            "https://aetherhub.com/User/Edinorog/", date(2026, 7, 20), "Pauper"
        )
        assert result is None
        scraper.get.assert_not_called()

    def test_find_tournament_url_rejects_non_user_url(self):
        with pytest.raises(ValueError, match="owner"):
            AetherhubService(scraper=MagicMock()).find_tournament_url(
                "https://aetherhub.com/Tourney/", date(2026, 7, 20), "Pauper"
            )

    def test_find_tournament_url_paginates_public_list(self):
        scraper = MagicMock()
        first = {
            "recordsFiltered": 2,
            "model": [
                {
                    "id": 1,
                    "name": "Паупер 21.07.2026",
                    "owner": "Edinorog",
                    "date": "2026-07-21T14:00:00",
                }
            ],
        }
        second = {
            "recordsFiltered": 2,
            "model": [
                {
                    "id": 2,
                    "name": "Паупер 20.07.2026",
                    "owner": "Edinorog",
                    "date": "2026-07-20T14:00:00",
                }
            ],
        }
        scraper.post.return_value.json.side_effect = [first, second]

        result = AetherhubService(scraper=scraper).find_tournament_url(
            "https://aetherhub.com/User/Edinorog/", date(2026, 7, 20), "Pauper"
        )

        assert result == "https://aetherhub.com/Tourney/RoundTourney/2"
        assert scraper.post.call_count == 2

    def test_find_tournament_url_rejects_ambiguous_result(self):
        scraper = MagicMock()
        scraper.post.return_value.json.return_value = {
            "recordsFiltered": 2,
            "model": [
                {
                    "id": tournament_id,
                    "name": "Паупер 20.07.2026",
                    "owner": "Edinorog",
                    "date": "2026-07-20T14:00:00",
                }
                for tournament_id in (1, 2)
            ],
        }

        with pytest.raises(ValueError, match="Multiple"):
            AetherhubService(scraper=scraper).find_tournament_url(
                "https://aetherhub.com/User/Edinorog/", date(2026, 7, 20), "Pauper"
            )

    def test_find_tournament_url_ignores_malformed_rows(self):
        scraper = MagicMock()
        scraper.post.return_value.json.return_value = {
            "recordsFiltered": 2,
            "model": [
                {"id": 1, "name": "Паупер", "owner": "Edinorog", "date": "bad-date"},
                {
                    "id": 2,
                    "name": "Паупер 19.07.2026",
                    "owner": "Edinorog",
                    "date": "2026-07-19T14:00:00",
                },
            ],
        }

        result = AetherhubService(scraper=scraper).find_tournament_url(
            "https://aetherhub.com/User/Edinorog/", date(2026, 7, 20), "Pauper"
        )

        assert result is None
        scraper.post.assert_called_once()

    def test_goldfish_date_only_name_is_pauper(self):
        scraper = MagicMock()
        scraper.post.return_value.json.return_value = {
            "recordsFiltered": 1,
            "model": [
                {
                    "id": 100796,
                    "name": "24.07",
                    "owner": "GoldFish",
                    "date": "2026-07-24T16:00:00",
                }
            ],
        }

        result = AetherhubService(scraper=scraper).find_tournament_url(
            "https://aetherhub.com/User/GoldFish", date(2026, 7, 24), "Pauper"
        )

        assert result == "https://aetherhub.com/Tourney/RoundTourney/100796"


class TestFindTodaysGoldfishStyle:
    """Goldfish: имя — просто дата, «паупер» стоит в подзаголовке «Constructed: Pauper Tourney»."""

    def _svc(self, html: str) -> AetherhubService:
        mock = MagicMock()
        mock.get.return_value.text = html
        return AetherhubService(scraper=mock)

    @pytest.mark.parametrize(
        "name,ago",
        [
            ("24.04", "4 hours ago"),  # реальный кейс Goldfish: дата в имени + создан сегодня
            ("24/04", "2 hours ago"),  # дата через слэш
            ("Паупер 24.04", "1 hour ago"),  # и «паупер», и дата
            ("паупер 24/04", "30 minutes ago"),
            ("Weekly", "an hour ago"),  # даты в имени нет — сегодня определяется по «создан час назад»
        ],
    )
    def test_todays_pauper_matched_by_subtitle_and_date(self, name, ago):
        html = _club_cards_html(
            [{"name": name, "url": "/Tourney/RoundTourney/100670", "subtitle": PAUPER_SUBTITLE, "ago": ago}]
        )
        result = self._svc(html).find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=TODAY)
        assert result == "https://aetherhub.com/Tourney/RoundTourney/100670"

    def test_yesterdays_pauper_not_matched(self):
        """«Паупер 23/04» на 24.04 — дата в имени вчерашняя, турнир не берётся."""
        html = _club_cards_html(
            [
                {
                    "name": "Паупер 23/04",
                    "url": "/Tourney/RoundTourney/100661",
                    "subtitle": PAUPER_SUBTITLE,
                    "ago": "1 day ago",
                }
            ]
        )
        result = self._svc(html).find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=TODAY)
        assert result is None

    def test_returns_first_freshest(self):
        """Список свежими сверху — берём первый сегодняшний паупер."""
        html = _club_cards_html(
            [
                {
                    "name": "24.04",
                    "url": "/Tourney/RoundTourney/100670",
                    "subtitle": PAUPER_SUBTITLE,
                    "ago": "4 hours ago",
                },
                {
                    "name": "Паупер 17/04",
                    "url": "/Tourney/RoundTourney/999",
                    "subtitle": PAUPER_SUBTITLE,
                    "ago": "7 days ago",
                },
            ]
        )
        result = self._svc(html).find_todays_pauper_tournament("https://aetherhub.com/User/GoldFish", today=TODAY)
        assert result == "https://aetherhub.com/Tourney/RoundTourney/100670"

    def test_incident_regression_100670_vs_100661(self):
        """Регрессия инцидента 17.07.2026 на реальной разметке: свежий «17.07» (100670,
        создан сегодня) против вчерашнего «Паупер 16/07» (100661). Оба паупер по подзаголовку,
        но 100661 датирован вчера (имя «16/07») — берётся 100670."""
        html = _club_cards_html(
            [
                {
                    "name": "17.07",
                    "url": "/Tourney/RoundTourney/100670",
                    "subtitle": PAUPER_SUBTITLE,
                    "ago": "4 hours ago",
                },
                {
                    "name": "Паупер 16/07",
                    "url": "/Tourney/RoundTourney/100661",
                    "subtitle": PAUPER_SUBTITLE,
                    "ago": "1 day ago",
                },
            ]
        )
        result = self._svc(html).find_todays_pauper_tournament(
            "https://aetherhub.com/User/GoldFish", today=date(2026, 7, 17)
        )
        assert result == "https://aetherhub.com/Tourney/RoundTourney/100670"

    def test_name_date_beats_misleading_hours_ago(self):
        """Даже если вчерашний вечерний турнир показан как «14 hours ago» (моложе суток),
        дата в имени «16/07» авторитетна и отсекает его — ровно защита от инцидента."""
        html = _club_cards_html(
            [
                {
                    "name": "17.07",
                    "url": "/Tourney/RoundTourney/100670",
                    "subtitle": PAUPER_SUBTITLE,
                    "ago": "2 hours ago",
                },
                {
                    "name": "Паупер 16/07",
                    "url": "/Tourney/RoundTourney/100661",
                    "subtitle": PAUPER_SUBTITLE,
                    "ago": "14 hours ago",
                },
            ]
        )
        result = self._svc(html).find_todays_pauper_tournament(
            "https://aetherhub.com/User/GoldFish", today=date(2026, 7, 17)
        )
        assert result == "https://aetherhub.com/Tourney/RoundTourney/100670"


class TestFindTodaysEdinorogStyle:
    """Edinorog: мультиформатный клуб, формат («Паупер»/«Легаси»/…) стоит в имени."""

    def _svc(self, html: str) -> AetherhubService:
        mock = MagicMock()
        mock.get.return_value.text = html
        return AetherhubService(scraper=mock)

    def _page(self) -> str:
        # как на реальной странице: свежие сверху, полные даты в имени
        return _club_cards_html(
            [
                {
                    "name": "Легаси 15.07.2026",
                    "url": "/Tourney/RoundTourney/100647",
                    "subtitle": PLAIN_SUBTITLE,
                    "ago": "2 days ago",
                },
                {
                    "name": "Пионер 14.07.2026",
                    "url": "/Tourney/RoundTourney/100638",
                    "subtitle": PLAIN_SUBTITLE,
                    "ago": "3 days ago",
                },
                {
                    "name": "Паупер 13.07.2026",
                    "url": "/Tourney/RoundTourney/100624",
                    "subtitle": PLAIN_SUBTITLE,
                    "ago": "4 days ago",
                },
                {
                    "name": "Модерн 10.07.2026",
                    "url": "/Tourney/RoundTourney/100552",
                    "subtitle": PLAIN_SUBTITLE,
                    "ago": "7 days ago",
                },
            ]
        )

    def test_picks_pauper_on_pauper_day(self):
        result = self._svc(self._page()).find_todays_pauper_tournament(
            "https://aetherhub.com/User/Edinorog/", today=date(2026, 7, 13)
        )
        assert result == "https://aetherhub.com/Tourney/RoundTourney/100624"

    def test_does_not_grab_todays_legacy(self):
        """15.07 — день Легаси (не паупер). Не хватаем сегодняшний Легаси, паупера сегодня нет."""
        result = self._svc(self._page()).find_todays_pauper_tournament(
            "https://aetherhub.com/User/Edinorog/", today=date(2026, 7, 15)
        )
        assert result is None

    @pytest.mark.parametrize(
        "other", ["Легаси 24.04.2026", "Пионер 24.04.2026", "Модерн 24.04.2026", "Винтаж 24.04.2026"]
    )
    def test_todays_non_pauper_russian_format_not_matched(self, other):
        html = _club_cards_html(
            [{"name": other, "url": "/Tourney/RoundTourney/1", "subtitle": PLAIN_SUBTITLE, "ago": "3 hours ago"}]
        )
        result = self._svc(html).find_todays_pauper_tournament("https://aetherhub.com/User/Edinorog/", today=TODAY)
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
    event_day_offset=0,
) -> AetherhubImportJob:
    club = Club(name="Goldfish", chat_id=0, aetherhub_url=aetherhub_url, schedules=[])
    schedule = ClubSchedule(
        weekday=weekday,
        game_time="19:30",
        aetherhub_fetch_times=fetch_times or ["21:00"],
        find_latest=find_latest,
    )
    return AetherhubImportJob(
        club,
        schedule,
        aetherhub_service=aetherhub_service,
        event_day_offset=event_day_offset,
    )


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

    def test_new_second_round_triggers_deferred_deck_reminder(self, db, svc):
        stored_url = "https://aetherhub.com/Tourney/RoundTourney/218"
        source = MagicMock()
        source.fetch_tournament.return_value = MagicMock()
        tournament = svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        svc.set_aetherhub_url(tournament.id, stored_url)
        job = _make_import_job(aetherhub_service=source)
        bot = AsyncMock()
        reminder = AsyncMock()

        with (
            patch("bot.scheduler.AetherhubImportService") as import_cls,
            patch("bot.scheduler.send_round_notifications", AsyncMock()),
            patch("bot.scheduler.send_deferred_deck_reminders", reminder),
            patch("bot.scheduler.maybe_announce_meta_gather_completed", AsyncMock()),
            patch("bot.scheduler.SessionLocal", return_value=MagicMock()),
        ):
            import_cls.return_value.import_tournament.return_value = MagicMock(
                registered=0,
                already_registered=2,
                pairings_saved=4,
                new_round_numbers=[2],
            )
            asyncio.run(job.run(now=FRIDAY_NOW, db=db, bot=bot))

        reminder.assert_awaited_once_with(
            bot,
            db,
            tournament.id,
            DeckReminderStage.ROUND2,
        )

    def test_stops_gracefully_when_club_page_has_no_tournament(self, db, svc):
        """If find_todays_pauper_tournament returns None, import is skipped."""
        mock_svc = MagicMock()
        mock_svc.find_todays_pauper_tournament.return_value = None

        svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        job = _make_import_job(aetherhub_service=mock_svc)
        asyncio.run(job.run(now=FRIDAY_NOW, db=db))

        mock_svc.fetch_tournament.assert_not_called()

    def test_does_not_import_or_save_auto_discovered_empty_tournament(self, db, svc):
        """An empty auto-discovered event must not become the tournament's stored URL."""
        found_url = "https://aetherhub.com/Tourney/RoundTourney/0"
        mock_svc = MagicMock()
        mock_svc.find_todays_pauper_tournament.return_value = found_url
        mock_svc.fetch_tournament.return_value = AetherhubTournamentData(url=found_url, players=[], rounds=[])

        svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))
        job = _make_import_job(aetherhub_service=mock_svc)

        with (
            patch("bot.scheduler.AetherhubImportService") as mock_import_cls,
            patch("bot.scheduler.TournamentService") as mock_ts_cls,
        ):
            asyncio.run(job.run(now=FRIDAY_NOW, db=db))

        mock_import_cls.return_value.import_tournament.assert_not_called()
        mock_ts_cls.return_value.set_aetherhub_url.assert_not_called()

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
        # DEBUG-клуб собирается в core.clubs (расписание переехало в БД, issue #124)
        with patch("core.clubs.settings") as mock_settings:
            mock_settings.DEBUG = True
            clubs = get_clubs()

        debug_clubs = [c for c in clubs if c.name == "Debug"]
        assert debug_clubs, "Debug club should exist when DEBUG=True"
        debug = debug_clubs[0]
        assert any(s.find_latest for s in debug.schedules)

    def test_debug_club_fetch_times(self):
        # DEBUG-клуб собирается в core.clubs (расписание переехало в БД, issue #124)
        with patch("core.clubs.settings") as mock_settings:
            mock_settings.DEBUG = True
            clubs = get_clubs()

        debug = next(c for c in clubs if c.name == "Debug")
        all_times = [t for s in debug.schedules for t in s.aetherhub_fetch_times]
        assert "12:31" in all_times

    def test_debug_club_has_aetherhub_url(self):
        # DEBUG-клуб собирается в core.clubs (расписание переехало в БД, issue #124)
        with patch("core.clubs.settings") as mock_settings:
            mock_settings.DEBUG = True
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

    def test_club_name_with_spaces_produces_url_safe_slug(self, db, svc):
        club = Club(name="Pair of dice", chat_id=0, schedules=[], title_prefix="🎲🎲 ")
        schedule = ClubSchedule(weekday="friday", game_time="19:30")

        asyncio.run(CreateTournamentJob(club, schedule).run(bot=None, now=FRIDAY_NOW, db=db))

        tournament = svc.get_active_tournament_for_chat(0)
        assert tournament.slug == "2026-04-24-pair-of-dice-pauper"

    def test_previous_day_job_uses_event_date_and_says_tomorrow(self, db, svc):
        club = Club(name="Pair of dice", chat_id=42, schedules=[], title_prefix="🎲🎲 ")
        schedule = ClubSchedule(
            weekday="tuesday",
            game_time="19:30",
            create_time="18:30",
            create_days_before=1,
        )
        monday = datetime(2026, 4, 27, 18, 30, tzinfo=TZ)

        with patch("bot.scheduler.send_registration_open", new_callable=AsyncMock) as announce:
            asyncio.run(CreateTournamentJob(club, schedule).run(bot=AsyncMock(), now=monday, db=db))

        tournament = svc.get_active_tournament_for_chat(42)
        assert tournament is not None
        assert tournament.title == "🎲🎲 Pair of dice Pauper 28.04.2026"
        assert tournament.slug == "2026-04-28-pair-of-dice-pauper"
        assert tournament.registration_close_at == datetime(2026, 4, 28, 16, 30)
        text = announce.await_args.args[-1]
        assert "завтра в 19:30" in text
        assert "сегодня" not in text

    def test_previous_day_job_does_not_run_on_event_weekday(self, db, svc):
        club = Club(name="Pair of dice", chat_id=42, schedules=[])
        schedule = ClubSchedule(weekday="tuesday", game_time="19:30", create_days_before=1)
        tuesday = datetime(2026, 4, 28, 18, 30, tzinfo=TZ)

        asyncio.run(CreateTournamentJob(club, schedule).run(bot=None, now=tuesday, db=db))

        assert svc.get_active_tournament_for_chat(42) is None

    def test_does_not_close_previous_active_tournament_or_create_next(self, db, svc):
        job = _make_create_job(weekday="friday", chat_id=0)
        old = svc.create_tournament(TournamentCreate(title="Old", chat_id=0, slug="old", club="Goldfish"))
        bot = AsyncMock()
        asyncio.run(job.run(bot=bot, now=FRIDAY_NOW, db=db))
        old_refreshed = db.get(cm.Tournament, old.id)
        assert old_refreshed.status == TournamentStatus.REGISTRATION
        assert old_refreshed.ended_at is None
        assert db.query(cm.Tournament).count() == 1
        bot.send_message.assert_not_awaited()

    def test_registration_open_goes_to_club_chat_and_owner_with_deeplink(self, db):
        job = _make_create_job(weekday="friday", chat_id=42)
        bot = AsyncMock()
        bot.get_me.return_value = MagicMock(username="TestBot")
        with patch("bot.scheduler.settings") as mock_settings:
            mock_settings.OWNER_CHAT_ID = 999
            asyncio.run(job.run(bot=bot, now=FRIDAY_NOW, db=db))
        # анонс регистрации ушёл и в чат клуба, и владельцу
        chats = {c.kwargs["chat_id"] for c in bot.send_message.call_args_list}
        assert chats == {42, 999}
        # с кнопкой-диплинком «Записать колоду»
        button = bot.send_message.call_args_list[0].kwargs["reply_markup"].inline_keyboard[0][0]
        assert button.url.startswith("https://t.me/TestBot?start=deck_")

    def test_registration_open_to_club_chat_even_without_owner(self, db):
        job = _make_create_job(weekday="friday", chat_id=42)
        bot = AsyncMock()
        bot.get_me.return_value = MagicMock(username="TestBot")
        with patch("bot.scheduler.settings") as mock_settings:
            mock_settings.OWNER_CHAT_ID = None
            asyncio.run(job.run(bot=bot, now=FRIDAY_NOW, db=db))
        chats = {c.kwargs["chat_id"] for c in bot.send_message.call_args_list}
        assert chats == {42}

    def test_no_registration_message_without_any_target(self, db):
        job = _make_create_job(weekday="friday", chat_id=0)  # нет ни группы клуба
        bot = AsyncMock()
        bot.get_me.return_value = MagicMock(username="TestBot")
        with patch("bot.scheduler.settings") as mock_settings:
            mock_settings.OWNER_CHAT_ID = None
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

    def test_after_midnight_import_runs_next_day_for_previous_event_date(self, db, svc):
        mock_svc = MagicMock()
        mock_svc.find_todays_pauper_tournament.return_value = None
        job = _make_import_job(
            weekday="friday",
            aetherhub_service=mock_svc,
            event_day_offset=1,
        )
        svc.create_tournament(TournamentCreate(title="T", chat_id=0, slug="t", club="Goldfish"))

        asyncio.run(job.run(now=SATURDAY_NOW.replace(hour=0, minute=30), db=db))

        mock_svc.find_todays_pauper_tournament.assert_called_once_with(
            job.club.aetherhub_url,
            today=FRIDAY_DATE,
        )


# ---------------------------------------------------------------------------
# format_schedule_text decomposition
# ---------------------------------------------------------------------------


class TestFormatScheduleText:
    def test_contains_club_name(self):
        text = format_schedule_text()
        assert "Goldfish" in text
        assert "Edinorog" in text

    def test_format_club_schedule_contains_weekday_and_times(self):
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
        club = Club(
            name="TestClub",
            chat_id=0,
            schedules=[ClubSchedule(weekday="monday", game_time="18:00")],
        )
        text = _format_club_schedule(club)
        assert "импорт" not in text
