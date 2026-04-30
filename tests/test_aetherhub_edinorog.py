"""Tests for Aetherhub edinorog format parser."""

from unittest.mock import Mock

import pytest

from services.aetherhub_parser_edinorog import AetherhubEdinorogParser


@pytest.fixture
def parser():
    return AetherhubEdinorogParser(scraper=Mock())


class TestIsbye:
    def test_uppercase(self, parser):
        assert parser._is_bye("BYE") is True

    def test_lowercase(self, parser):
        assert parser._is_bye("bye") is True

    def test_mixed(self, parser):
        assert parser._is_bye("Bye") is True

    def test_player_name(self, parser):
        assert parser._is_bye("Иванов Иван") is False

    def test_empty(self, parser):
        assert parser._is_bye("") is False


class TestParsePage:
    def _html(self, pairings_rows: str, standings_rows: str = "") -> str:
        return f"""<html><body>
        <table>
          <tr><th>Table</th><th>Player 1</th><th>Player 2</th></tr>
          {pairings_rows}
        </table>
        <table>
          <tr><th>Rank</th><th>Name</th></tr>
          {standings_rows}
        </table>
        <a href="?p=1">1</a>
        </body></html>"""

    def test_bye_not_added_as_player_in_pairings(self, parser):
        html = self._html("<tr><td>1</td><td>Иванов (9 Points)</td><td>BYE</td></tr>")
        players, pairings, _ = parser._parse_page(html)
        player_names = [p.player for p in pairings]
        assert "BYE" not in player_names

    def test_bye_stored_as_none_opponent(self, parser):
        html = self._html("<tr><td>1</td><td>Иванов</td><td>BYE</td></tr>")
        _, pairings, _ = parser._parse_page(html)
        assert len(pairings) == 1
        assert pairings[0].player == "Иванов"
        assert pairings[0].opponent is None

    def test_bye_case_insensitive(self, parser):
        html = self._html("<tr><td>1</td><td>Alice</td><td>Bye</td></tr>")
        _, pairings, _ = parser._parse_page(html)
        assert all(p.player != "Bye" for p in pairings)
        assert pairings[0].opponent is None

    def test_normal_pairing_bidirectional(self, parser):
        html = self._html("<tr><td>1</td><td>Alice</td><td>Bob</td></tr>")
        _, pairings, _ = parser._parse_page(html)
        by_player = {p.player: p.opponent for p in pairings}
        assert by_player["Alice"] == "Bob"
        assert by_player["Bob"] == "Alice"

    def test_bye_not_in_standings_players(self, parser):
        html = self._html(
            "",
            "<tr><td>1</td><td>Alice</td></tr><tr><td>2</td><td>BYE</td></tr>",
        )
        players, _, _ = parser._parse_page(html)
        assert "BYE" not in players
        assert "Alice" in players
