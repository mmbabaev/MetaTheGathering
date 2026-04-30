"""Tests for aetherhub scraper and import service."""

from unittest.mock import MagicMock

import pytest

from services.aetherhub_import_service import AetherhubImportService
from services.aetherhub_models import AetherhubPairing, AetherhubRound, AetherhubTournamentData
from services.aetherhub_service import AetherhubService

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_data(players, rounds_pairings):
    rounds = [
        AetherhubRound(number=i + 1, pairings=[AetherhubPairing(player=p, opponent=o) for p, o in pairs])
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


def _svc(html_by_url: dict[str, str]) -> AetherhubService:
    return AetherhubService(scraper=_mock_scraper(html_by_url))


# ── Sample HTML fixtures ─────────────────────────────────────────────────────

# Main tournament page: standings table + navigation links
STANDINGS_HTML = """
<html><body>
<span id="numberOfRounds">Rounds 2</span>
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

STANDINGS_EMPTY_HTML = """
<html><body>
<span id="numberOfRounds">Rounds 1</span>
<table>
  <tr><th>Rank</th><th>Name</th><th>Points</th></tr>
</table>
<a href="?p=1">1</a>
</body></html>
"""

# AJAX pairings endpoint responses (one table: Table, Player 1, Player 2)
PAIRINGS_R1_HTML = """
<html><body>
<table>
  <tr><th>Table</th><th>Player 1</th><th>Player 2</th><th></th></tr>
  <tr><td>1</td><td>Alice (3 Points)</td><td>Bob (3 Points)</td><td>2-1</td></tr>
  <tr><td>2</td><td>Carol (0 Points)</td><td></td><td></td></tr>
</table>
</body></html>
"""

PAIRINGS_R2_HTML = """
<html><body>
<table>
  <tr><th>Table</th><th>Player 1</th><th>Player 2</th><th></th></tr>
  <tr><td>1</td><td>Bob (3 Points)</td><td>Carol (3 Points)</td><td>2-0</td></tr>
</table>
</body></html>
"""


# ── TestStripPoints ──────────────────────────────────────────────────────────


class TestStripPoints:
    svc = AetherhubService()

    def test_removes_points_suffix(self):
        assert self.svc._strip_points("Иванов Иван (9 Points)") == "Иванов Иван"

    def test_removes_points_in_middle(self):
        assert self.svc._strip_points("Валентин (6 Points) Задорожний") == "Валентин Задорожний"

    def test_removes_points_case_insensitive(self):
        assert self.svc._strip_points("Валентин (6 points) Задорожний") == "Валентин Задорожний"
        assert self.svc._strip_points("Валентин (6 POINTS) Задорожний") == "Валентин Задорожний"

    def test_removes_singular_point(self):
        assert self.svc._strip_points("Петров Петр (1 Point)") == "Петров Петр"

    def test_no_suffix_unchanged(self):
        assert self.svc._strip_points("Сидоров Сидор") == "Сидоров Сидор"

    def test_strips_leading_trailing_whitespace(self):
        assert self.svc._strip_points("  Иванов Иван  ") == "Иванов Иван"

    def test_empty_string(self):
        assert self.svc._strip_points("") == ""


# ── TestParseStandingsPage ───────────────────────────────────────────────────


class TestParseStandingsPage:
    svc = AetherhubService()

    def test_extracts_all_players(self):
        players, _ = self.svc._parse_standings_page(STANDINGS_HTML)
        assert set(players) == {"Alice", "Bob", "Carol"}

    def test_detects_max_round_from_nav_links(self):
        _, max_round = self.svc._parse_standings_page(STANDINGS_HTML)
        assert max_round == 2

    def test_no_nav_links_defaults_to_round_1(self):
        html = "<html><body><table><tr><th>Rank</th><th>Name</th></tr></table></body></html>"
        _, max_round = self.svc._parse_standings_page(html)
        assert max_round == 1

    def test_empty_standings_returns_empty_list(self):
        players, _ = self.svc._parse_standings_page(STANDINGS_EMPTY_HTML)
        assert players == []

    def test_no_tables_returns_empty(self):
        players, max_round = self.svc._parse_standings_page("<html><body></body></html>")
        assert players == []
        assert max_round == 1


# ── TestParsePairingsPage ────────────────────────────────────────────────────


class TestParsePairingsPage:
    svc = AetherhubService()

    def test_pairings_both_directions(self):
        pairings = self.svc._parse_pairings_page(PAIRINGS_R1_HTML)
        by_player = {p.player: p.opponent for p in pairings}
        assert by_player["Alice"] == "Bob"
        assert by_player["Bob"] == "Alice"

    def test_bye_stored_as_none_opponent(self):
        pairings = self.svc._parse_pairings_page(PAIRINGS_R1_HTML)
        carol = next(p for p in pairings if p.player == "Carol")
        assert carol.opponent is None

    def test_points_stripped_from_names(self):
        pairings = self.svc._parse_pairings_page(PAIRINGS_R1_HTML)
        for p in pairings:
            assert "Points" not in p.player
            if p.opponent:
                assert "Points" not in p.opponent

    def test_empty_table_returns_empty(self):
        html = "<html><body><table><tr><th>Table</th><th>Player 1</th><th>Player 2</th></tr></table></body></html>"
        assert self.svc._parse_pairings_page(html) == []

    def test_no_tables_returns_empty(self):
        assert self.svc._parse_pairings_page("<html><body></body></html>") == []

    def test_bye_as_p2_not_added_as_player(self):
        html = """<html><body><table>
          <tr><th>Table</th><th>Player 1</th><th>Player 2</th></tr>
          <tr><td>1</td><td>Alice</td><td>BYE</td></tr>
        </table></body></html>"""
        pairings = self.svc._parse_pairings_page(html)
        players = [p.player for p in pairings]
        assert "BYE" not in players
        assert len(pairings) == 1
        assert pairings[0].player == "Alice"
        assert pairings[0].opponent is None

    def test_bye_case_insensitive(self):
        html = """<html><body><table>
          <tr><th>Table</th><th>Player 1</th><th>Player 2</th></tr>
          <tr><td>1</td><td>Alice</td><td>Bye</td></tr>
        </table></body></html>"""
        pairings = self.svc._parse_pairings_page(html)
        assert all(p.player != "Bye" for p in pairings)
        assert pairings[0].opponent is None


# ── TestFetchTournament ──────────────────────────────────────────────────────


_BASE_URL = "https://aetherhub.com/Tourney/RoundTourney/1"
_PAIRINGS_R1 = "https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id=1&p=1"
_PAIRINGS_R2 = "https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id=1&p=2"


class TestFetchTournament:
    def _fetch(self, url=_BASE_URL):
        tid = url.rstrip("/").split("/")[-1]
        html_map = {
            url: STANDINGS_HTML,
            f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={tid}&p=1": PAIRINGS_R1_HTML,
            f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={tid}&p=2": PAIRINGS_R2_HTML,
        }
        return _svc(html_map).fetch_tournament(url)

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
        data = self._fetch()
        assert data.url == _BASE_URL

    def test_players_from_pairings_when_standings_empty(self):
        """When standings are empty, player names are taken from round 1 pairings."""
        data = _svc({_BASE_URL: STANDINGS_EMPTY_HTML, _PAIRINGS_R1: PAIRINGS_R1_HTML}).fetch_tournament(_BASE_URL)
        assert set(data.players) == {"Alice", "Bob", "Carol"}

    def test_players_taken_from_round1_even_if_main_page_has_subset(self):
        """Filled tournaments can show only a subset of players on the default page; we must use round 1."""
        main_html_subset = """
        <html><body>
        <span id="numberOfRounds">Rounds 1</span>
        <table>
          <tr><th>Rank</th><th>Name</th><th>Points</th></tr>
          <tr><td>1</td><td>Alice (3 Points)</td><td>3</td></tr>
          <tr><td>2</td><td>Bob (3 Points)</td><td>3</td></tr>
        </table>
        </body></html>
        """
        # Pairings contain Carol too; also points are injected in labels.
        pairings_html = """
        <html><body>
        <table>
          <tr><th>Table</th><th>Player 1</th><th>Player 2</th><th></th></tr>
          <tr><td>1</td><td>Alice (3 Points)</td><td>Bob (3 Points)</td><td>2-1</td></tr>
          <tr><td>2</td><td>Carol (0 Points)</td><td></td><td></td></tr>
        </table>
        </body></html>
        """
        data = _svc({_BASE_URL: main_html_subset, _PAIRINGS_R1: pairings_html}).fetch_tournament(_BASE_URL)
        assert set(data.players) == {"Alice", "Bob", "Carol"}

    def test_99049_real_html_round4_subset_but_round1_has_all_12(self):
        """Regression: real Aetherhub HTML for 99049.

        For filled tournaments the default main page shows 'Pairings round 4' and a subset in standings,
        but round 1 pairings still contain the full participant list. We must take players from round 1.
        """
        from pathlib import Path

        base_url = "https://aetherhub.com/Tourney/RoundTourney/99049"
        tid = "99049"

        fixtures_dir = Path(__file__).resolve().parents[1] / "scripts" / "aetherhub" / "fixtures"
        main_path = fixtures_dir / "99049_main.html"
        p1_path = fixtures_dir / "99049_pairings_p1.html"
        p2_path = fixtures_dir / "99049_pairings_p2.html"
        p3_path = fixtures_dir / "99049_pairings_p3.html"
        p4_path = fixtures_dir / "99049_pairings_p4.html"

        missing = [p for p in [main_path, p1_path, p2_path, p3_path, p4_path] if not p.exists()]
        if missing:
            pytest.skip("Real 99049 fixtures are missing. Run: python3 scripts/aetherhub/fetch_99049_fixtures.py")

        html_map = {
            base_url: main_path.read_text(encoding="utf-8"),
            f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={tid}&p=1": p1_path.read_text(
                encoding="utf-8"
            ),
            f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={tid}&p=2": p2_path.read_text(
                encoding="utf-8"
            ),
            f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={tid}&p=3": p3_path.read_text(
                encoding="utf-8"
            ),
            f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={tid}&p=4": p4_path.read_text(
                encoding="utf-8"
            ),
        }

        data = _svc(html_map).fetch_tournament(base_url)

        assert len(data.rounds) == 4
        assert len(data.players) == 12
        assert all("Points" not in p for p in data.players)

    def test_invalid_url_raises(self):
        import pytest

        with pytest.raises(ValueError):
            AetherhubService().fetch_tournament("https://aetherhub.com/Tourney/RoundTourney/")


# ── TestFindUserByName ───────────────────────────────────────────────────────


@pytest.fixture
def import_svc(db):
    return AetherhubImportService(db)


class TestFindUserByName:
    def test_finds_user_by_first_name(self, import_svc, user_alice):
        result = import_svc.find_user_by_name("Alice")
        assert result is not None
        assert result.id == user_alice.id

    def test_returns_none_for_unknown(self, import_svc):
        assert import_svc.find_user_by_name("Unknown Person") is None

    def test_returns_none_for_empty(self, import_svc):
        assert import_svc.find_user_by_name("") is None

    def test_finds_user_with_reversed_name_order(self, import_svc, db):
        from services.user import UserService

        UserService(db).get_or_create(tg_id=9001, username=None, first_name="Михаил", last_name="Бабаев")
        result = import_svc.find_user_by_name("Бабаев Михаил")
        assert result is not None
        assert result.first_name == "Михаил"
        assert result.last_name == "Бабаев"

    def test_finds_user_with_canonical_name_order(self, import_svc, db):
        from services.user import UserService

        UserService(db).get_or_create(tg_id=9002, username=None, first_name="Иван", last_name="Петров")
        result = import_svc.find_user_by_name("Иван Петров")
        assert result is not None
        assert result.first_name == "Иван"

    def test_finds_user_when_points_injected_and_case_mixed(self, import_svc, db):
        from services.user import UserService

        UserService(db).get_or_create(tg_id=9003, username=None, first_name="Валентин", last_name="Задорожний")
        result = import_svc.find_user_by_name("Валентин (6 points) Задорожний")
        assert result is not None
        assert result.first_name == "Валентин"
        assert result.last_name == "Задорожний"


# ── TestSavePairings ─────────────────────────────────────────────────────────


class TestSavePairings:
    def test_saves_pairings_to_db(self, import_svc, tournament):
        rounds = [
            AetherhubRound(
                number=1,
                pairings=[
                    AetherhubPairing(player="Alice", opponent="Bob"),
                    AetherhubPairing(player="Bob", opponent="Alice"),
                ],
            )
        ]
        count = import_svc._save_pairings(tournament.id, rounds)
        assert count == 2

    def test_idempotent_second_save_returns_zero(self, import_svc, tournament):
        rounds = [
            AetherhubRound(
                number=1,
                pairings=[
                    AetherhubPairing(player="Alice", opponent="Bob"),
                ],
            )
        ]
        import_svc._save_pairings(tournament.id, rounds)
        count2 = import_svc._save_pairings(tournament.id, rounds)
        assert count2 == 0

    def test_saves_bye_as_none(self, import_svc, tournament):
        rounds = [
            AetherhubRound(
                number=1,
                pairings=[
                    AetherhubPairing(player="Alice", opponent=None),
                ],
            )
        ]
        import_svc._save_pairings(tournament.id, rounds)
        assert import_svc.get_opponent(tournament.id, "Alice", round_number=1) is None


# ── TestImportTournament ─────────────────────────────────────────────────────


class TestImportTournament:
    def test_registers_matched_user(self, import_svc, tournament, user_alice):
        data = _make_data(players=["Alice"], rounds_pairings=[[("Alice", None)]])
        result = import_svc.import_tournament(tournament.id, data)
        assert result.registered == 1
        assert result.created_names == []

    def test_unmatched_name_creates_placeholder_and_registers(self, import_svc, tournament):
        data = _make_data(players=["Ghost User"], rounds_pairings=[[("Ghost User", None)]])
        result = import_svc.import_tournament(tournament.id, data)
        assert result.registered == 1
        assert "Ghost User" in result.created_names

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
        data = _make_data(
            players=[],
            rounds_pairings=[
                [("Alice", "Bob")],
                [("Bob", "Carol")],
            ],
        )
        import_svc.import_tournament(tournament.id, data)
        assert len(import_svc.get_pairings(tournament.id)) == 2

    def test_filters_by_round(self, import_svc, tournament):
        data = _make_data(
            players=[],
            rounds_pairings=[
                [("Alice", "Bob")],
                [("Bob", "Carol")],
            ],
        )
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


# ── TestGetUnfilledOpponents ─────────────────────────────────────────────────


class TestGetUnfilledOpponents:
    """Tests for get_unfilled_opponents — covers all error keys and success path."""

    def _setup(self, import_svc, svc, tournament, db, player_name: str, opponent_name: str):
        """Import pairings and register both players; return (player_user, opponent_participant)."""
        from services.user import UserService

        data = _make_data(
            players=[player_name, opponent_name],
            rounds_pairings=[[(player_name, opponent_name), (opponent_name, player_name)]],
        )
        import_svc.import_tournament(tournament.id, data)
        user_svc = UserService(db)
        player = user_svc.find_by_name(player_name) or user_svc.get_or_create(
            tg_id=5001, username=None, first_name=player_name
        )
        opponent = user_svc.find_by_name(opponent_name) or user_svc.get_or_create(
            tg_id=5002, username=None, first_name=opponent_name
        )
        participants = svc.list_participants_for_tournament(tournament.id)
        return player, opponent, participants

    def test_no_pairings_returns_error_key(self, import_svc, svc, tournament):
        participants = svc.list_participants_for_tournament(tournament.id)
        result, err = import_svc.get_unfilled_opponents(tournament.id, 999, participants)
        assert result == []
        assert err == "no_pairings"

    def test_not_in_pairings_returns_error_key(self, import_svc, svc, tournament, user_alice, db):
        data = _make_data(players=["Bob"], rounds_pairings=[[("Bob", None)]])
        import_svc.import_tournament(tournament.id, data)
        participants = svc.list_participants_for_tournament(tournament.id)
        # user_alice is not in pairings
        result, err = import_svc.get_unfilled_opponents(tournament.id, user_alice.id, participants)
        assert result == []
        assert err == "not_in_pairings"

    def test_all_filled_returns_error_key(self, import_svc, svc, tournament, db):
        from services.archetype import ArchetypeService
        from services.user import UserService

        data = _make_data(
            players=["PlayerA", "PlayerB"],
            rounds_pairings=[[("PlayerA", "PlayerB"), ("PlayerB", "PlayerA")]],
        )
        import_svc.import_tournament(tournament.id, data)
        user_svc = UserService(db)
        arch_svc = ArchetypeService(db)
        player_a = user_svc.find_by_name("PlayerA")
        player_b = user_svc.find_by_name("PlayerB")
        arch = arch_svc.get_or_create_by_name("Burn")
        # Give opponent (PlayerB) an archetype
        p_b = svc.get_participant(tournament.id, player_b.id)
        svc.set_participant_archetype(participant_id=p_b.id, archetype_id=arch.id)
        participants = svc.list_participants_for_tournament(tournament.id)
        result, err = import_svc.get_unfilled_opponents(tournament.id, player_a.id, participants)
        assert result == []
        assert err == "all_filled"

    def test_returns_unfilled_opponents(self, import_svc, svc, tournament, db):
        from services.user import UserService

        data = _make_data(
            players=["PlayerA", "PlayerB"],
            rounds_pairings=[[("PlayerA", "PlayerB"), ("PlayerB", "PlayerA")]],
        )
        import_svc.import_tournament(tournament.id, data)
        user_svc = UserService(db)
        player_a = user_svc.find_by_name("PlayerA")
        player_b = user_svc.find_by_name("PlayerB")
        participants = svc.list_participants_for_tournament(tournament.id)
        result, err = import_svc.get_unfilled_opponents(tournament.id, player_a.id, participants)
        assert err is None
        assert len(result) == 1
        assert result[0].user_id == player_b.id


# ── TestImportTournamentValidation ───────────────────────────────────────────


class TestImportTournamentValidation:
    """import_tournament must reject invalid tournament states."""

    def test_raises_on_nonexistent_tournament(self, import_svc):
        from services.errors import TournamentNotFound

        data = _make_data(players=[], rounds_pairings=[])
        with pytest.raises(TournamentNotFound):
            import_svc.import_tournament(99999, data)

    def test_raises_on_closed_tournament(self, import_svc, svc, tournament):
        from services.errors import TournamentInvalidState

        svc.close_tournament(tournament.id)
        data = _make_data(players=[], rounds_pairings=[])
        with pytest.raises(TournamentInvalidState):
            import_svc.import_tournament(tournament.id, data)

    def test_allows_import_into_open_tournament(self, import_svc, tournament):
        data = _make_data(players=[], rounds_pairings=[])
        result = import_svc.import_tournament(tournament.id, data)
        assert result.registered == 0


# ── TestSavePairingsUpsert ───────────────────────────────────────────────────


class TestSavePairingsUpsert:
    """_save_pairings updates existing bye → real opponent on re-import."""

    def test_updates_bye_to_opponent_on_reimport(self, import_svc, tournament):
        rounds_with_bye = [AetherhubRound(number=1, pairings=[AetherhubPairing(player="Alice", opponent=None)])]
        import_svc._save_pairings(tournament.id, rounds_with_bye)
        assert import_svc.get_opponent(tournament.id, "Alice", 1) is None

        rounds_with_opp = [AetherhubRound(number=1, pairings=[AetherhubPairing(player="Alice", opponent="Bob")])]
        count = import_svc._save_pairings(tournament.id, rounds_with_opp)
        assert count == 1
        assert import_svc.get_opponent(tournament.id, "Alice", 1) == "Bob"

    def test_no_update_when_opponent_unchanged(self, import_svc, tournament):
        rounds = [AetherhubRound(number=1, pairings=[AetherhubPairing(player="Alice", opponent="Bob")])]
        import_svc._save_pairings(tournament.id, rounds)
        count = import_svc._save_pairings(tournament.id, rounds)
        assert count == 0
