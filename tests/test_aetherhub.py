"""Tests for aetherhub scraper and import service."""

from unittest.mock import patch, MagicMock

import pytest

from services.aetherhub import (
    fetch_tournament,
    AetherhubTournamentData,
    AetherhubRound,
    AetherhubPairing,
    _strip_points,
    _parse_page,
)
from services.aetherhub_import import AetherhubImportService


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_data(players, rounds_pairings):
    rounds = [
        AetherhubRound(number=i + 1, pairings=[
            AetherhubPairing(player=p, opponent=o) for p, o in pairs
        ])
        for i, pairs in enumerate(rounds_pairings)
    ]
    return AetherhubTournamentData(
        url="https://aetherhub.com/Tourney/RoundTourney/1",
        players=players,
        rounds=rounds,
    )


def _mock_scraper(html_by_url: dict[str, str]):
    scraper = MagicMock()

    def get(url, **kwargs):
        resp = MagicMock()
        resp.text = html_by_url.get(url, "<html><body><table></table><table></table></body></html>")
        return resp

    scraper.get.side_effect = get
    return scraper


# ── Sample HTML fixtures ─────────────────────────────────────────────────────

ROUND1_HTML = """
<html><body>
<table>
  <tr><th>Table</th><th>Player 1</th><th>Player 2</th><th>Result</th></tr>
  <tr><td>1</td><td>Alice (3 Points)</td><td>Bob (3 Points)</td><td>2-1</td></tr>
  <tr><td>2</td><td>Carol (0 Points)</td><td></td><td></td></tr>
</table>
<table>
  <tr><th>Rank</th><th>Name</th><th>Points</th></tr>
  <tr><td>1</td><td>Alice</td><td>3</td></tr>
  <tr><td>2</td><td>Bob</td><td>3</td></tr>
  <tr><td>3</td><td>Carol</td><td>0</td></tr>
</table>
<a href="?p=1">1</a>
<a href="?p=2">2</a>
</body></html>
"""

ROUND2_HTML = """
<html><body>
<table>
  <tr><th>Table</th><th>Player 1</th><th>Player 2</th><th>Result</th></tr>
  <tr><td>1</td><td>Bob (3 Points)</td><td>Carol (3 Points)</td><td>2-0</td></tr>
</table>
<table>
  <tr><th>Rank</th><th>Name</th><th>Points</th></tr>
  <tr><td>1</td><td>Alice</td><td>6</td></tr>
  <tr><td>2</td><td>Bob</td><td>6</td></tr>
  <tr><td>3</td><td>Carol</td><td>3</td></tr>
</table>
<a href="?p=1">1</a>
<a href="?p=2">2</a>
</body></html>
"""


# ── TestStripPoints ──────────────────────────────────────────────────────────

class TestStripPoints:
    def test_removes_points_suffix(self):
        assert _strip_points("Иванов Иван (9 Points)") == "Иванов Иван"

    def test_removes_singular_point(self):
        assert _strip_points("Петров Петр (1 Point)") == "Петров Петр"

    def test_no_suffix_unchanged(self):
        assert _strip_points("Сидоров Сидор") == "Сидоров Сидор"

    def test_strips_leading_trailing_whitespace(self):
        assert _strip_points("  Иванов Иван  ") == "Иванов Иван"

    def test_empty_string(self):
        assert _strip_points("") == ""


# ── TestParsePage ────────────────────────────────────────────────────────────

class TestParsePage:
    def test_extracts_all_players_from_standings(self):
        players, _, _ = _parse_page(ROUND1_HTML)
        assert set(players) == {"Alice", "Bob", "Carol"}

    def test_pairings_both_directions(self):
        _, pairings, _ = _parse_page(ROUND1_HTML)
        by_player = {p.player: p.opponent for p in pairings}
        assert by_player["Alice"] == "Bob"
        assert by_player["Bob"] == "Alice"

    def test_bye_stored_as_none_opponent(self):
        _, pairings, _ = _parse_page(ROUND1_HTML)
        carol = next(p for p in pairings if p.player == "Carol")
        assert carol.opponent is None

    def test_detects_max_round_from_nav_links(self):
        _, _, max_round = _parse_page(ROUND1_HTML)
        assert max_round == 2

    def test_no_nav_links_defaults_to_round_1(self):
        html = "<html><body><table><tr><th>Table</th><th>Player 1</th><th>Player 2</th></tr></table><table></table></body></html>"
        _, _, max_round = _parse_page(html)
        assert max_round == 1

    def test_empty_tables_return_empty_lists(self):
        html = "<html><body><table><tr><th>h</th></tr></table><table><tr><th>h</th></tr></table></body></html>"
        players, pairings, _ = _parse_page(html)
        assert players == []
        assert pairings == []

    def test_points_stripped_from_pairing_names(self):
        _, pairings, _ = _parse_page(ROUND1_HTML)
        for p in pairings:
            assert "Points" not in p.player
            if p.opponent:
                assert "Points" not in p.opponent


# ── TestFetchTournament ──────────────────────────────────────────────────────

class TestFetchTournament:
    def _fetch(self, url="https://aetherhub.com/Tourney/RoundTourney/1"):
        html_map = {f"{url}?p=1": ROUND1_HTML, f"{url}?p=2": ROUND2_HTML}
        with patch("services.aetherhub._scraper", return_value=_mock_scraper(html_map)):
            return fetch_tournament(url)

    def test_players_taken_from_round1_standings(self):
        data = self._fetch()
        assert set(data.players) == {"Alice", "Bob", "Carol"}

    def test_fetches_all_rounds(self):
        data = self._fetch()
        assert len(data.rounds) == 2
        assert [r.number for r in data.rounds] == [1, 2]

    def test_round1_pairings_correct(self):
        data = self._fetch()
        r1 = data.rounds[0]
        by_player = {p.player: p.opponent for p in r1.pairings}
        assert by_player["Alice"] == "Bob"
        assert by_player["Carol"] is None  # bye

    def test_round2_pairings_correct(self):
        data = self._fetch()
        r2 = data.rounds[1]
        by_player = {p.player: p.opponent for p in r2.pairings}
        assert by_player["Bob"] == "Carol"

    def test_url_preserved(self):
        url = "https://aetherhub.com/Tourney/RoundTourney/1"
        data = self._fetch(url)
        assert data.url == url

    def test_single_round_tournament(self):
        url = "https://aetherhub.com/Tourney/RoundTourney/1"
        single_round_html = ROUND1_HTML.replace(
            '<a href="?p=2">2</a>', ""
        )
        html_map = {f"{url}?p=1": single_round_html}
        with patch("services.aetherhub._scraper", return_value=_mock_scraper(html_map)):
            data = fetch_tournament(url)
        assert len(data.rounds) == 1


# ── TestFindUserByName ───────────────────────────────────────────────────────

@pytest.fixture
def import_svc(db):
    return AetherhubImportService(db)


class TestFindUserByName:
    def test_finds_user_by_first_name(self, import_svc, user_alice):
        result = import_svc._find_user_by_name("Alice")
        assert result is not None
        assert result.id == user_alice.id

    def test_returns_none_for_unknown(self, import_svc):
        assert import_svc._find_user_by_name("Unknown Person") is None

    def test_returns_none_for_empty(self, import_svc):
        assert import_svc._find_user_by_name("") is None


# ── TestSavePairings ─────────────────────────────────────────────────────────

class TestSavePairings:
    def test_saves_pairings_to_db(self, import_svc, tournament):
        rounds = [AetherhubRound(number=1, pairings=[
            AetherhubPairing(player="Alice", opponent="Bob"),
            AetherhubPairing(player="Bob", opponent="Alice"),
        ])]
        count = import_svc._save_pairings(tournament.id, rounds)
        assert count == 2

    def test_idempotent_second_save_returns_zero(self, import_svc, tournament):
        rounds = [AetherhubRound(number=1, pairings=[
            AetherhubPairing(player="Alice", opponent="Bob"),
        ])]
        import_svc._save_pairings(tournament.id, rounds)
        count2 = import_svc._save_pairings(tournament.id, rounds)
        assert count2 == 0

    def test_saves_bye_as_none(self, import_svc, tournament):
        rounds = [AetherhubRound(number=1, pairings=[
            AetherhubPairing(player="Alice", opponent=None),
        ])]
        import_svc._save_pairings(tournament.id, rounds)
        assert import_svc.get_opponent(tournament.id, "Alice", round_number=1) is None


# ── TestImportTournament ─────────────────────────────────────────────────────

class TestImportTournament:
    def test_registers_matched_user(self, import_svc, tournament, user_alice):
        data = _make_data(players=["Alice"], rounds_pairings=[[("Alice", None)]])
        result = import_svc.import_tournament(tournament.id, data)
        assert result.registered == 1
        assert result.unmatched_names == []

    def test_unmatched_name_not_registered(self, import_svc, tournament):
        data = _make_data(players=["Ghost User"], rounds_pairings=[[("Ghost User", None)]])
        result = import_svc.import_tournament(tournament.id, data)
        assert result.registered == 0
        assert "Ghost User" in result.unmatched_names

    def test_already_registered_counted_separately(self, import_svc, svc, tournament, user_alice):
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
        data = _make_data(players=["Alice"], rounds_pairings=[[("Alice", None)]])
        result = import_svc.import_tournament(tournament.id, data)
        assert result.registered == 0
        assert result.already_registered == 1

    def test_pairings_saved_for_all_rounds(self, import_svc, tournament):
        data = _make_data(
            players=[],
            rounds_pairings=[
                [("Alice", "Bob"), ("Bob", "Alice")],
                [("Carol", "Alice"), ("Alice", "Carol")],
            ],
        )
        result = import_svc.import_tournament(tournament.id, data)
        assert result.pairings_saved == 4

    def test_idempotent(self, import_svc, tournament, user_alice):
        data = _make_data(players=["Alice"], rounds_pairings=[[("Alice", None)]])
        import_svc.import_tournament(tournament.id, data)
        r2 = import_svc.import_tournament(tournament.id, data)
        assert r2.registered == 0
        assert r2.already_registered == 1
        assert r2.pairings_saved == 0


# ── TestGetPairings ──────────────────────────────────────────────────────────

class TestGetPairings:
    def test_returns_all_rounds(self, import_svc, tournament):
        data = _make_data(players=[], rounds_pairings=[
            [("Alice", "Bob")],
            [("Bob", "Carol")],
        ])
        import_svc.import_tournament(tournament.id, data)
        assert len(import_svc.get_pairings(tournament.id)) == 2

    def test_filters_by_round(self, import_svc, tournament):
        data = _make_data(players=[], rounds_pairings=[
            [("Alice", "Bob")],
            [("Bob", "Carol")],
        ])
        import_svc.import_tournament(tournament.id, data)
        r1 = import_svc.get_pairings(tournament.id, round_number=1)
        assert len(r1) == 1
        assert r1[0].round_number == 1

    def test_empty_when_no_pairings(self, import_svc, tournament):
        assert import_svc.get_pairings(tournament.id) == []


# ── TestGetOpponent ──────────────────────────────────────────────────────────

class TestGetOpponent:
    def test_returns_opponent(self, import_svc, tournament):
        data = _make_data(players=[], rounds_pairings=[[("Alice", "Bob")]])
        import_svc.import_tournament(tournament.id, data)
        assert import_svc.get_opponent(tournament.id, "Alice", 1) == "Bob"

    def test_returns_none_for_unknown_player(self, import_svc, tournament):
        assert import_svc.get_opponent(tournament.id, "Nobody", 1) is None

    def test_returns_none_for_unknown_round(self, import_svc, tournament):
        data = _make_data(players=[], rounds_pairings=[[("Alice", "Bob")]])
        import_svc.import_tournament(tournament.id, data)
        assert import_svc.get_opponent(tournament.id, "Alice", round_number=99) is None

    def test_bye_returns_none(self, import_svc, tournament):
        data = _make_data(players=[], rounds_pairings=[[("Alice", None)]])
        import_svc.import_tournament(tournament.id, data)
        assert import_svc.get_opponent(tournament.id, "Alice", 1) is None
