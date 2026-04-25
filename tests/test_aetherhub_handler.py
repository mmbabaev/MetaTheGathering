"""Tests for AetherhubHandler business logic."""

from unittest.mock import MagicMock

import pytest

from bot.handlers.aetherhub import AetherhubFetchResult, AetherhubHandler
from services.aetherhub_models import AetherhubTournamentData


def _make_tournament_data(url: str = "https://aetherhub.com/Tourney/RoundTourney/1") -> AetherhubTournamentData:
    return AetherhubTournamentData(url=url, players=["Alice", "Bob"], rounds=[])


def _handler(find_url: str | None = None, fetch_data: AetherhubTournamentData | None = None) -> AetherhubHandler:
    svc = MagicMock()
    svc.find_todays_pauper_tournament.return_value = find_url
    svc.fetch_tournament.return_value = fetch_data or _make_tournament_data()
    return AetherhubHandler(svc)


class TestHandleImportPrompt:
    def test_uses_stored_url_without_club_lookup(self):
        stored = "https://aetherhub.com/Tourney/RoundTourney/42"
        h = _handler(find_url="https://other.url")
        result = h.handle_import_prompt(stored_url=stored, club_aetherhub_url="https://club.url")
        h._aetherhub.find_todays_pauper_tournament.assert_not_called()
        h._aetherhub.fetch_tournament.assert_called_once_with(stored)
        assert result is not None

    def test_stored_url_header_is_update(self):
        stored = "https://aetherhub.com/Tourney/RoundTourney/42"
        h = _handler()
        result = h.handle_import_prompt(stored_url=stored, club_aetherhub_url=None)
        assert "Обновление" in result.preview_text

    def test_auto_finds_url_when_no_stored(self):
        found = "https://aetherhub.com/Tourney/RoundTourney/99"
        h = _handler(find_url=found)
        result = h.handle_import_prompt(stored_url=None, club_aetherhub_url="https://club.url")
        h._aetherhub.find_todays_pauper_tournament.assert_called_once_with("https://club.url")
        h._aetherhub.fetch_tournament.assert_called_once_with(found)
        assert result is not None

    def test_auto_find_header_is_import(self):
        h = _handler(find_url="https://aetherhub.com/Tourney/RoundTourney/99")
        result = h.handle_import_prompt(stored_url=None, club_aetherhub_url="https://club.url")
        assert "Импорт" in result.preview_text

    def test_returns_none_when_no_stored_and_not_found(self):
        h = _handler(find_url=None)
        result = h.handle_import_prompt(stored_url=None, club_aetherhub_url="https://club.url")
        assert result is None
        h._aetherhub.fetch_tournament.assert_not_called()

    def test_returns_none_when_no_stored_and_no_club_url(self):
        h = _handler()
        result = h.handle_import_prompt(stored_url=None, club_aetherhub_url=None)
        assert result is None
        h._aetherhub.find_todays_pauper_tournament.assert_not_called()
        h._aetherhub.fetch_tournament.assert_not_called()

    def test_result_url_matches_fetched_tournament(self):
        url = "https://aetherhub.com/Tourney/RoundTourney/55"
        h = _handler(fetch_data=_make_tournament_data(url=url))
        result = h.handle_import_prompt(stored_url=url, club_aetherhub_url=None)
        assert result.data.url == url
