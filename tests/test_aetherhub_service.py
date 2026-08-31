"""Tests for aetherhub scraper and import service."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from core import models
from core.models import Participant
from core.schemas import TournamentCreate
from services.aetherhub_import_service import AetherhubImportService
from services.aetherhub_models import AetherhubPairing, AetherhubRound, AetherhubTournamentData
from services.aetherhub_service import AetherhubService
from services.archetype import ArchetypeService
from services.errors import TournamentInvalidState, TournamentNotFound
from services.user import UserService

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_data(players, rounds_pairings, standings=None):
    rounds = [
        AetherhubRound(number=i + 1, pairings=[AetherhubPairing(player=p, opponent=o) for p, o in pairs])
        for i, pairs in enumerate(rounds_pairings)
    ]
    return AetherhubTournamentData(
        url="https://aetherhub.com/Tourney/RoundTourney/1",
        players=players,
        rounds=rounds,
        standings=standings or [],
    )


def _late_entry_data(*, standings=None):
    """Вуйцицкий опоздал ко второму раунду и вошёл в турнир с техническим поражением."""
    return AetherhubTournamentData(
        url="x",
        players=["Гасанлы Фарид", "Хрипков Сергей"],
        rounds=[
            AetherhubRound(
                number=1,
                pairings=[
                    AetherhubPairing(
                        player="Гасанлы Фарид",
                        opponent="Хрипков Сергей",
                        player_wins=0,
                        opponent_wins=2,
                    ),
                    AetherhubPairing(
                        player="Хрипков Сергей",
                        opponent="Гасанлы Фарид",
                        player_wins=2,
                        opponent_wins=0,
                    ),
                ],
            ),
            AetherhubRound(
                number=2,
                pairings=[
                    AetherhubPairing(
                        player="Гасанлы Фарид",
                        opponent="Вуйцицкий Владимир",
                        player_wins=2,
                        opponent_wins=0,
                    ),
                    AetherhubPairing(
                        player="Вуйцицкий Владимир",
                        opponent="Гасанлы Фарид",
                        player_wins=0,
                        opponent_wins=2,
                    ),
                ],
            ),
        ],
        standings=standings or [],
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


def test_import_merges_safe_real_and_placeholder_duplicate(db, svc, arch_svc):
    """A split AetherHub name must collapse an existing one-field Telegram duplicate."""
    tournament = svc.create_tournament(TournamentCreate(title="Duplicate roster", chat_id=184))
    real = UserService(db).get_or_create(tg_id=184001, first_name="Антон Ильин")
    placeholder = models.User(tg_id=-184001, first_name="Антон", last_name="Ильин")
    deck = arch_svc.get_or_create_by_name("Burn")
    db.add(placeholder)
    db.flush()
    db.add(models.Participant(tournament_id=tournament.id, user_id=real.id))
    db.add(models.Participant(tournament_id=tournament.id, user_id=placeholder.id, archetype_id=deck.id))
    db.commit()

    data = _make_data(players=["Антон Ильин"], rounds_pairings=[], standings=["Антон Ильин"])
    AetherhubImportService(db).import_tournament(tournament.id, data)

    participants = (
        db.execute(select(models.Participant).where(models.Participant.tournament_id == tournament.id)).scalars().all()
    )
    assert len(participants) == 1
    assert participants[0].user_id == real.id
    assert participants[0].archetype_id == deck.id
    assert participants[0].final_place == 1
    assert db.get(models.User, placeholder.id) is None


def test_import_does_not_auto_merge_when_multiple_real_users_share_name(db):
    first = UserService(db).get_or_create(tg_id=185001, first_name="Иван Иванов")
    second = UserService(db).get_or_create(tg_id=185002, first_name="Иван", last_name="Иванов")
    placeholder = models.User(tg_id=-185001, first_name="Иван", last_name="Иванов")
    db.add(placeholder)
    db.commit()

    resolved = UserService(db).resolve_and_merge_import_name("Иван Иванов")

    assert resolved.id in {first.id, second.id, placeholder.id}
    assert db.get(models.User, first.id) is not None
    assert db.get(models.User, second.id) is not None
    assert db.get(models.User, placeholder.id) is not None


def test_import_matches_unique_registered_player_with_single_name_typo(db, svc, arch_svc):
    """Issue #233: «Констанин» in AetherHub is the registered «Константин»."""
    tournament = svc.create_tournament(TournamentCreate(title="Goldfish 14.08", chat_id=233))
    real = UserService(db).get_or_create(
        tg_id=233001,
        first_name="Константин",
        last_name="Бурбаев",
    )
    deck = arch_svc.get_or_create_by_name("Jeskai Ephemerate")
    svc.register_participant(tournament_id=tournament.id, user_id=real.id, archetype_id=deck.id)
    data = _make_data(
        players=["Бурбаев Констанин"],
        rounds_pairings=[[("Бурбаев Констанин", None)]],
        standings=["Бурбаев Констанин"],
    )

    result = AetherhubImportService(db).import_tournament(tournament.id, data)

    participants = (
        db.execute(select(models.Participant).where(models.Participant.tournament_id == tournament.id)).scalars().all()
    )
    assert result.created_names == []
    assert len(participants) == 1
    assert participants[0].user_id == real.id
    assert participants[0].archetype_id == deck.id
    assert participants[0].final_place == 1
    standing = AetherhubImportService(db).get_standings(tournament.id)[0]
    assert standing.display_name == "Бурбаев Константин"
    assert standing.archetype_name == "Jeskai Ephemerate"


def test_import_repairs_existing_typo_placeholder_without_replacing_real_name(db, svc, arch_svc):
    """Повторный импорт сам схлопывает уже созданный issue #233 placeholder."""
    tournament = svc.create_tournament(TournamentCreate(title="Goldfish 14.08", chat_id=234))
    real = UserService(db).get_or_create(
        tg_id=234001,
        first_name="Константин",
        last_name="Бурбаев",
    )
    placeholder = models.User(tg_id=-234001, first_name="Бурбаев", last_name="Констанин")
    deck = arch_svc.get_or_create_by_name("Jeskai Ephemerate")
    db.add(placeholder)
    db.flush()
    db.add(models.Participant(tournament_id=tournament.id, user_id=real.id, archetype_id=deck.id))
    db.add(models.Participant(tournament_id=tournament.id, user_id=placeholder.id, final_place=3))
    db.commit()
    placeholder_id = placeholder.id
    data = _make_data(
        players=["Бурбаев Констанин"],
        rounds_pairings=[],
        standings=["Бурбаев Констанин"],
    )

    AetherhubImportService(db).import_tournament(tournament.id, data)

    participant = db.execute(
        select(models.Participant).where(models.Participant.tournament_id == tournament.id)
    ).scalar_one()
    assert participant.user_id == real.id
    assert participant.archetype_id == deck.id
    assert participant.final_place == 1
    assert db.get(models.User, placeholder_id) is None
    db.refresh(real)
    assert (real.first_name, real.last_name) == ("Константин", "Бурбаев")


def test_import_does_not_guess_when_single_typo_match_is_ambiguous(db, svc, arch_svc):
    tournament = svc.create_tournament(TournamentCreate(title="Ambiguous typo", chat_id=235))
    deck = arch_svc.get_or_create_by_name("Burn")
    for tg_id, first_name in ((235001, "Мария"), (235002, "Марина")):
        user = UserService(db).get_or_create(tg_id=tg_id, first_name=first_name, last_name="Иванова")
        svc.register_participant(tournament_id=tournament.id, user_id=user.id, archetype_id=deck.id)
    data = _make_data(
        players=["Иванова Мариа"],
        rounds_pairings=[],
        standings=["Иванова Мариа"],
    )

    result = AetherhubImportService(db).import_tournament(tournament.id, data)

    participants = (
        db.execute(select(models.Participant).where(models.Participant.tournament_id == tournament.id)).scalars().all()
    )
    assert result.created_names == ["Иванова Мариа"]
    assert len(participants) == 3
    assert sum(participant.user.tg_id < 0 for participant in participants) == 1


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
<table id='matchList'>
  <tr><th>Table</th><th>Player 1</th><th>Player 2</th><th></th></tr>
  <tr><td>1</td><td>Alice (3 Points)</td><td>Bob (3 Points)</td><td>2-1</td></tr>
  <tr><td>2</td><td>Carol (0 Points)</td><td></td><td></td></tr>
</table>
</body></html>
"""

PAIRINGS_R2_HTML = """
<html><body>
<table id='matchList'>
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
        html = "<html><body><table id='matchList'><tr><th>Table</th><th>Player 1</th><th>Player 2</th></tr></table></body></html>"
        assert self.svc._parse_pairings_page(html) == []

    def test_no_tables_returns_empty(self):
        assert self.svc._parse_pairings_page("<html><body></body></html>") == []

    def test_bye_as_p2_not_added_as_player(self):
        html = """<html><body><table id='matchList'>
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
        html = """<html><body><table id='matchList'>
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
        <table id='matchList'>
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
        with pytest.raises(ValueError):
            AetherhubService().fetch_tournament("https://aetherhub.com/Tourney/RoundTourney/")


# ── TestFindUserByName ───────────────────────────────────────────────────────


@pytest.fixture
def import_svc(db):
    return AetherhubImportService(db)


class TestPhantomRoundCleanup:
    """import_tournament self-heals stale phantom rounds (round_number > real max)."""

    def _stale_round(self, db, tournament_id, round_number):
        db.add(
            models.RoundPairing(
                tournament_id=tournament_id,
                round_number=round_number,
                player_name="Alice",
                opponent_name="Bob",
            )
        )

    def test_deletes_rounds_above_real_max(self, import_svc, tournament, db):
        # leftovers from an earlier buggy import: rounds 5 and 6 duplicate round 4
        for rn in (1, 2, 3, 4, 5, 6):
            self._stale_round(db, tournament.id, rn)
        db.commit()

        data = _make_data(players=[], rounds_pairings=[[("Alice", "Bob")] for _ in range(4)])
        import_svc.import_tournament(tournament.id, data)

        assert import_svc.get_round_numbers(tournament.id) == [1, 2, 3, 4]

    def test_keeps_all_rounds_when_no_phantoms(self, import_svc, tournament, db):
        data = _make_data(players=[], rounds_pairings=[[("Alice", "Bob")] for _ in range(4)])
        import_svc.import_tournament(tournament.id, data)
        assert import_svc.get_round_numbers(tournament.id) == [1, 2, 3, 4]

    def test_no_deletion_when_data_has_no_rounds(self, import_svc, tournament, db):
        # stale rounds must NOT be wiped if the fresh import returned nothing
        for rn in (1, 2):
            self._stale_round(db, tournament.id, rn)
        db.commit()
        data = _make_data(players=[], rounds_pairings=[])
        import_svc.import_tournament(tournament.id, data)
        assert import_svc.get_round_numbers(tournament.id) == [1, 2]


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
        UserService(db).get_or_create(tg_id=9001, username=None, first_name="Михаил", last_name="Бабаев")
        result = import_svc.find_user_by_name("Бабаев Михаил")
        assert result is not None
        assert result.first_name == "Михаил"
        assert result.last_name == "Бабаев"

    def test_finds_user_with_canonical_name_order(self, import_svc, db):
        UserService(db).get_or_create(tg_id=9002, username=None, first_name="Иван", last_name="Петров")
        result = import_svc.find_user_by_name("Иван Петров")
        assert result is not None
        assert result.first_name == "Иван"

    def test_finds_user_when_points_injected_and_case_mixed(self, import_svc, db):
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

    def test_registers_player_present_only_in_final_standings(self, import_svc, db, tournament, user_svc):
        """Issue #184: round-one roster had 23 names while final standings had 24."""
        missing = user_svc.get_or_create(
            tg_id=396,
            first_name="Владимир",
            last_name="Вуйцицкий",
        )
        data = AetherhubTournamentData(
            url="x",
            players=["Хрипков Сергей"],
            rounds=[],
            standings=["Хрипков Сергей", "Вуйцицкий Владимир"],
        )

        result = import_svc.import_tournament(tournament.id, data)

        participant = (
            db.query(models.Participant)
            .filter_by(
                tournament_id=tournament.id,
                user_id=missing.id,
            )
            .one()
        )
        assert participant.final_place == 2
        assert result.players_received == 2
        assert result.registered == 2

    def test_registers_late_entry_from_second_round_with_loss(self, import_svc, db, tournament, user_svc):
        """#65: опоздун отсутствует в roster/R1 и впервые появляется в R2 со счётом 0:2."""
        missing = user_svc.get_or_create(
            tg_id=396,
            first_name="Владимир",
            last_name="Вуйцицкий",
        )
        result = import_svc.import_tournament(tournament.id, _late_entry_data())

        participant = (
            db.query(models.Participant)
            .filter_by(
                tournament_id=tournament.id,
                user_id=missing.id,
            )
            .one()
        )
        assert participant.final_place is None
        assert result.players_received == 3
        assert result.registered == 3
        assert db.query(models.Participant).filter_by(tournament_id=tournament.id).count() == 3
        pairing = (
            db.query(models.RoundPairing)
            .filter_by(
                tournament_id=tournament.id,
                round_number=2,
                player_name="Вуйцицкий Владимир",
            )
            .one()
        )
        assert (pairing.player_wins, pairing.opponent_wins) == (0, 2)

    def test_final_standings_update_same_late_entry_without_duplicate(self, import_svc, db, tournament, user_svc):
        missing = user_svc.get_or_create(
            tg_id=396,
            first_name="Владимир",
            last_name="Вуйцицкий",
        )
        import_svc.import_tournament(tournament.id, _late_entry_data())

        result = import_svc.import_tournament(
            tournament.id,
            _late_entry_data(standings=["Хрипков Сергей", "Вуйцицкий Владимир", "Гасанлы Фарид"]),
        )

        participants = (
            db.query(models.Participant)
            .filter_by(
                tournament_id=tournament.id,
                user_id=missing.id,
            )
            .all()
        )
        assert len(participants) == 1
        assert participants[0].final_place == 2
        assert result.registered == 0
        assert result.already_registered == 3

    def test_final_import_keeps_second_round_bye_entry_and_removes_no_show(
        self, import_svc, db, tournament, user_svc, svc, caplog
    ):
        """#221: a late entrant is real; a bot-only registration is not a result row."""
        late = user_svc.get_or_create(
            tg_id=22101,
            first_name="Михаил",
            last_name="Бабаев",
        )
        no_show = user_svc.get_or_create(
            tg_id=22102,
            first_name="Владислав",
            last_name="Старостин",
        )
        svc.register_participant(tournament_id=tournament.id, user_id=no_show.id)
        data = AetherhubTournamentData(
            url="x",
            players=["Ашаров Вадим", "Батуев Виталий"],
            rounds=[
                AetherhubRound(
                    number=1,
                    pairings=[
                        AetherhubPairing(
                            player="Ашаров Вадим",
                            opponent="Батуев Виталий",
                            player_wins=2,
                            opponent_wins=0,
                        ),
                        AetherhubPairing(
                            player="Батуев Виталий",
                            opponent="Ашаров Вадим",
                            player_wins=0,
                            opponent_wins=2,
                        ),
                    ],
                ),
                AetherhubRound(
                    number=2,
                    pairings=[
                        AetherhubPairing(
                            player="Бабаев Михаил",
                            opponent=None,
                            player_wins=2,
                            opponent_wins=0,
                        ),
                    ],
                ),
            ],
            standings=["Ашаров Вадим", "Бабаев Михаил", "Батуев Виталий"],
        )

        with caplog.at_level("INFO", logger="services.aetherhub_import_service"):
            import_svc.import_tournament(tournament.id, data)

        late_participant = (
            db.query(models.Participant)
            .filter_by(
                tournament_id=tournament.id,
                user_id=late.id,
            )
            .one()
        )
        assert late_participant.final_place == 2
        assert (
            db.query(models.Participant).filter_by(tournament_id=tournament.id, user_id=no_show.id).one_or_none()
            is None
        )
        assert "Старостин Владислав" in caplog.text

    def test_does_not_remove_bot_only_registration_before_scores_are_complete(
        self, import_svc, db, tournament, user_svc, svc
    ):
        no_show = user_svc.get_or_create(
            tg_id=22103,
            first_name="Владислав",
            last_name="Старостин",
        )
        svc.register_participant(tournament_id=tournament.id, user_id=no_show.id)
        data = AetherhubTournamentData(
            url="x",
            players=["Ашаров Вадим", "Батуев Виталий"],
            rounds=[
                AetherhubRound(
                    number=1,
                    pairings=[
                        AetherhubPairing(
                            player="Ашаров Вадим",
                            opponent="Батуев Виталий",
                        ),
                    ],
                )
            ],
            standings=["Ашаров Вадим", "Батуев Виталий"],
        )

        import_svc.import_tournament(tournament.id, data)

        assert (
            db.query(models.Participant)
            .filter_by(
                tournament_id=tournament.id,
                user_id=no_show.id,
            )
            .one()
        )

    def test_players_and_standings_name_order_does_not_double_count(self, import_svc, tournament, user_svc):
        user_svc.get_or_create(tg_id=396, first_name="Владимир", last_name="Вуйцицкий")
        data = AetherhubTournamentData(
            url="x",
            players=["Владимир Вуйцицкий"],
            rounds=[],
            standings=["Вуйцицкий Владимир"],
        )

        result = import_svc.import_tournament(tournament.id, data)

        assert result.registered == 1
        assert result.already_registered == 0

    def test_already_registered_counted_separately(self, import_svc, svc, tournament, user_alice):
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
        data = _make_data(players=["Alice"], rounds_pairings=[[("Alice", None)]])
        result = import_svc.import_tournament(tournament.id, data)
        assert result.registered == 0
        assert result.already_registered == 1

    def test_tracks_seen_players_without_marking_absent_registration(
        self, import_svc, svc, db, tournament, user_alice, user_svc
    ):
        absent = user_svc.get_or_create(tg_id=27301, first_name="Owl", last_name="Player")
        svc.register_participant(tournament_id=tournament.id, user_id=absent.id)

        import_svc.import_tournament(
            tournament.id,
            _make_data(players=["Alice"], rounds_pairings=[[("Alice", None)]]),
        )

        seen_participant = svc.get_participant(tournament.id, user_alice.id)
        absent_participant = svc.get_participant(tournament.id, absent.id)
        assert seen_participant.aetherhub_seen_at is not None
        assert absent_participant.aetherhub_seen_at is None

    def test_later_import_marks_player_and_partial_import_does_not_clear(
        self, import_svc, svc, db, tournament, user_alice, user_svc
    ):
        late = user_svc.get_or_create(tg_id=27302, first_name="Late", last_name="Player")
        svc.register_participant(tournament_id=tournament.id, user_id=late.id)
        import_svc.import_tournament(
            tournament.id,
            _make_data(players=["Alice"], rounds_pairings=[[("Alice", None)]]),
        )
        assert svc.get_participant(tournament.id, late.id).aetherhub_seen_at is None

        import_svc.import_tournament(
            tournament.id,
            _make_data(players=["Alice", "Late Player"], rounds_pairings=[]),
        )
        marked_at = svc.get_participant(tournament.id, late.id).aetherhub_seen_at
        assert marked_at is not None

        import_svc.import_tournament(tournament.id, _make_data(players=[], rounds_pairings=[]))
        assert svc.get_participant(tournament.id, late.id).aetherhub_seen_at == marked_at

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

    def test_closed_tournament_refreshes_scores_without_raising(self, import_svc, db, tournament):
        # импортируем пары пока турнир открыт (счёта ещё нет)
        import_svc.import_tournament(
            tournament.id,
            _make_data(players=[], rounds_pairings=[[("Alice", "Bob"), ("Bob", "Alice")]]),
        )
        db.get(models.Tournament, tournament.id).status = models.TournamentStatus.CLOSED
        db.commit()

        # реимпорт закрытого со счётом — не падает, обновляет счёт, без перерегистрации/уведомлений
        scored = AetherhubTournamentData(
            url="x",
            players=[],
            rounds=[
                AetherhubRound(
                    number=1,
                    pairings=[
                        AetherhubPairing(player="Alice", opponent="Bob", player_wins=2, opponent_wins=1),
                        AetherhubPairing(player="Bob", opponent="Alice", player_wins=1, opponent_wins=2),
                    ],
                )
            ],
        )
        result = import_svc.import_tournament(tournament.id, scored)
        assert result.registered == 0
        assert result.new_round_numbers == []
        p = db.query(models.RoundPairing).filter_by(tournament_id=tournament.id, player_name="Alice").first()
        assert (p.player_wins, p.opponent_wins) == (2, 1)


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
        assert result[0].participant.user_id == player_b.id
        assert result[0].round_number == 1

    def test_returns_opponents_sorted_by_round(self, import_svc, svc, tournament, db):
        # PlayerA faces B in round 1 and C in round 2 → result ordered by round
        data = _make_data(
            players=["PlayerA", "PlayerB", "PlayerC"],
            rounds_pairings=[
                [("PlayerA", "PlayerB"), ("PlayerB", "PlayerA")],
                [("PlayerA", "PlayerC"), ("PlayerC", "PlayerA")],
            ],
        )
        import_svc.import_tournament(tournament.id, data)
        user_svc = UserService(db)
        player_a = user_svc.find_by_name("PlayerA")
        player_b = user_svc.find_by_name("PlayerB")
        player_c = user_svc.find_by_name("PlayerC")
        participants = svc.list_participants_for_tournament(tournament.id)
        result, err = import_svc.get_unfilled_opponents(tournament.id, player_a.id, participants)
        assert err is None
        assert [(o.round_number, o.participant.user_id) for o in result] == [
            (1, player_b.id),
            (2, player_c.id),
        ]


# ── TestImportTournamentValidation ───────────────────────────────────────────


class TestImportTournamentValidation:
    """import_tournament must reject invalid tournament states."""

    def test_raises_on_nonexistent_tournament(self, import_svc):
        data = _make_data(players=[], rounds_pairings=[])
        with pytest.raises(TournamentNotFound):
            import_svc.import_tournament(99999, data)

    def test_closed_tournament_refreshes_pairings_no_register(self, import_svc, svc, tournament):
        # закрытый турнир не реджектится: обновляет паринги/счёт, но не регистрирует
        svc.close_tournament(tournament.id)
        data = _make_data(players=["Alice"], rounds_pairings=[[("Alice", "Bob"), ("Bob", "Alice")]])
        result = import_svc.import_tournament(tournament.id, data)
        assert result.registered == 0
        assert result.already_registered == 0
        assert result.new_round_numbers == []
        assert result.pairings_saved == 2

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


# ── TestParseStandingsOrder ──────────────────────────────────────────────────


class TestParseStandingsOrder:
    """Part 1: standings are parsed in rank order from the main tournament page."""

    svc = AetherhubService()

    STANDINGS_WITH_POINTS_HTML = """
    <html><body>
    <span id="numberOfRounds">Rounds 3</span>
    <table>
      <tr><th>Rank</th><th>Name</th><th>Points</th></tr>
      <tr><td>1</td><td>Carol (9 Points)</td><td>9</td></tr>
      <tr><td>2</td><td>Alice (6 Points)</td><td>6</td></tr>
      <tr><td>3</td><td>Bob (3 Points)</td><td>3</td></tr>
    </table>
    <a href="?p=1">1</a><a href="?p=2">2</a><a href="?p=3">3</a>
    </body></html>
    """

    def test_standings_returned_in_rank_order(self):
        players, _ = self.svc._parse_standings_page(self.STANDINGS_WITH_POINTS_HTML)
        assert players == ["Carol", "Alice", "Bob"]

    def test_points_stripped_from_standings_names(self):
        players, _ = self.svc._parse_standings_page(self.STANDINGS_WITH_POINTS_HTML)
        assert all("Points" not in name for name in players)

    def test_fetch_tournament_populates_standings(self):
        tid = "1"
        base = f"https://aetherhub.com/Tourney/RoundTourney/{tid}"
        p1_url = f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={tid}&p=1"
        data = _svc({base: self.STANDINGS_WITH_POINTS_HTML, p1_url: PAIRINGS_R1_HTML}).fetch_tournament(base)
        assert data.standings == ["Carol", "Alice", "Bob"]

    def test_fetch_tournament_standings_empty_when_no_table_data(self):
        tid = "1"
        base = f"https://aetherhub.com/Tourney/RoundTourney/{tid}"
        p1_url = f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={tid}&p=1"
        data = _svc({base: STANDINGS_EMPTY_HTML, p1_url: PAIRINGS_R1_HTML}).fetch_tournament(base)
        assert data.standings == []

    def test_players_still_from_round1_pairings_regardless_of_standings(self):
        """players field must not be affected by standings; it comes from round 1 pairings."""
        tid = "1"
        base = f"https://aetherhub.com/Tourney/RoundTourney/{tid}"
        p1_url = f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={tid}&p=1"
        # standings has 2 players, pairings has 3
        data = _svc({base: self.STANDINGS_WITH_POINTS_HTML, p1_url: PAIRINGS_R1_HTML}).fetch_tournament(base)
        assert set(data.players) == {"Alice", "Bob", "Carol"}


# ── TestImportFinalPlace ─────────────────────────────────────────────────────


class TestImportFinalPlace:
    """Part 2: final_place is saved to DB from standings during import."""

    def _participant(self, db, tournament_id, user_id):
        return db.execute(
            select(models.Participant).where(
                models.Participant.tournament_id == tournament_id,
                models.Participant.user_id == user_id,
            )
        ).scalar_one_or_none()

    def test_final_place_assigned_from_standings_order(self, import_svc, db, tournament, user_alice):
        data = _make_data(
            players=["Alice"],
            rounds_pairings=[[("Alice", None)]],
            standings=["Alice"],
        )
        import_svc.import_tournament(tournament.id, data)
        p = self._participant(db, tournament.id, user_alice.id)
        assert p.final_place == 1

    def test_first_in_standings_gets_place_1(self, import_svc, db, tournament, user_alice, user_bob):
        data = _make_data(
            players=["Alice", "Bob"],
            rounds_pairings=[[("Alice", "Bob"), ("Bob", "Alice")]],
            standings=["Bob", "Alice"],
        )
        import_svc.import_tournament(tournament.id, data)
        alice = self._participant(db, tournament.id, user_alice.id)
        bob = self._participant(db, tournament.id, user_bob.id)
        assert bob.final_place == 1
        assert alice.final_place == 2

    def test_final_place_null_when_standings_empty(self, import_svc, db, tournament, user_alice):
        data = _make_data(
            players=["Alice"],
            rounds_pairings=[[("Alice", None)]],
            standings=[],
        )
        import_svc.import_tournament(tournament.id, data)
        p = self._participant(db, tournament.id, user_alice.id)
        assert p.final_place is None

    def test_final_place_updated_on_reimport(self, import_svc, svc, db, tournament, user_alice):
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
        data = _make_data(
            players=["Alice"],
            rounds_pairings=[[("Alice", None)]],
            standings=["Alice"],
        )
        import_svc.import_tournament(tournament.id, data)
        p = self._participant(db, tournament.id, user_alice.id)
        assert p.final_place == 1

    def test_final_place_updated_for_closed_tournament(self, import_svc, svc, db, tournament, user_alice):
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
        svc.close_tournament(tournament.id)
        data = _make_data(players=["Alice"], rounds_pairings=[], standings=["Alice"])
        import_svc.import_tournament(tournament.id, data)
        assert self._participant(db, tournament.id, user_alice.id).final_place == 1

    def test_empty_standings_do_not_clear_existing_place(self, import_svc, svc, db, tournament, user_alice):
        participant = svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
        db.get(models.Participant, participant.id).final_place = 4
        db.commit()
        data = _make_data(players=["Alice"], rounds_pairings=[], standings=[])
        import_svc.import_tournament(tournament.id, data)
        assert self._participant(db, tournament.id, user_alice.id).final_place == 4

    def test_bye_not_counted_in_place_numbering(self, import_svc, db, tournament, user_alice, user_bob):
        data = _make_data(
            players=["Alice", "Bob"],
            rounds_pairings=[[("Alice", "Bob"), ("Bob", "Alice")]],
            standings=["Alice", "BYE", "Bob"],
        )
        import_svc.import_tournament(tournament.id, data)
        alice = self._participant(db, tournament.id, user_alice.id)
        bob = self._participant(db, tournament.id, user_bob.id)
        assert alice.final_place == 1
        assert bob.final_place == 3  # BYE occupies index 1, Bob is index 2 → place 3


# ── TestParseStandingsFromTabResults ─────────────────────────────────────────
# Regression: completed tournaments embed round-N pairings in tab_pairings (first
# in the DOM), so tables[0] was the pairings table — not the final standings.
# The fix: prefer div#tab_results over tables[0].


# HTML matching the real structure of a completed tournament (e.g. 99291):
# tab_pairings has the last-round pairing table (wrong source for standings),
# tab_results has the final standings table (correct).
COMPLETED_TOURNAMENT_HTML = """
<html><body>
<div id="tab_pairings">
  <table id='matchList'>
    <tr><th>Table</th><th>Player 1</th><th>Player 2</th><th>Result</th></tr>
    <tr><td>1</td><td>Рябинин Андрей (9 Points)</td><td>Хрипков Сергей (9 Points)</td><td>2-0</td></tr>
    <tr><td>2</td><td>Федулов Ринат (9 Points)</td><td>Кузнецов Ярослав (9 Points)</td><td>2-0</td></tr>
    <tr><td>3</td><td>Юдин Антон (7 Points)</td><td>BYE</td><td></td></tr>
  </table>
</div>
<div id="tab_results">
  <table>
    <tr><th>Rank</th><th>Name</th><th>Points</th></tr>
    <tr><td>1</td><td>Федулов Ринат</td><td>12</td></tr>
    <tr><td>2</td><td>Рябинин Андрей</td><td>12</td></tr>
    <tr><td>3</td><td>Юдин Антон</td><td>10</td></tr>
    <tr><td>4</td><td>Хрипков Сергей</td><td>9</td></tr>
    <tr><td>5</td><td>Кузнецов Ярослав</td><td>9</td></tr>
  </table>
</div>
<a href="?p=1">1</a>
<a href="?p=2">2</a>
<a href="?p=3">3</a>
<a href="?p=4">4</a>
</body></html>
"""


class TestParseStandingsFromTabResults:
    svc = AetherhubService()

    def test_reads_standings_from_tab_results_not_pairings(self):
        players, _ = self.svc._parse_standings_page(COMPLETED_TOURNAMENT_HTML)
        # Pairings table (tab_pairings) has 3 rows with Player1 + Player2 mixed.
        # Standings table (tab_results) has 5 players in rank order.
        assert players == ["Федулов Ринат", "Рябинин Андрей", "Юдин Антон", "Хрипков Сергей", "Кузнецов Ярослав"]

    def test_pairings_players_not_included_in_standings(self):
        # If we were reading from tab_pairings (cells[1] only), we'd get only
        # Рябинин, Федулов, Юдин — 3 players, not 5.
        players, _ = self.svc._parse_standings_page(COMPLETED_TOURNAMENT_HTML)
        assert len(players) == 5

    def test_max_round_from_nav_links(self):
        _, max_round = self.svc._parse_standings_page(COMPLETED_TOURNAMENT_HTML)
        assert max_round == 4

    def test_bye_not_in_standings(self):
        players, _ = self.svc._parse_standings_page(COMPLETED_TOURNAMENT_HTML)
        assert "BYE" not in players
        assert all("BYE" not in p.upper() for p in players)

    def test_fallback_to_first_table_when_no_tab_results(self):
        html = """<html><body>
        <table>
          <tr><th>Rank</th><th>Name</th></tr>
          <tr><td>1</td><td>Alice</td></tr>
          <tr><td>2</td><td>Bob</td></tr>
        </table>
        </body></html>"""
        players, _ = self.svc._parse_standings_page(html)
        assert players == ["Alice", "Bob"]


# ── TestParseNumRoundsFromLinks ───────────────────────────────────────────────


class TestParseNumRoundsFromLinks:
    svc = AetherhubService()

    def test_reads_rounds_from_nav_links_when_no_span_or_data_page(self):
        # 99291-style: no numberOfRounds span, no data-page, but ?p=N links
        html = """<html><body>
        <div id="tab_pairings"><table></table></div>
        <a href="?p=1">1</a>
        <a href="?p=2">2</a>
        <a href="?p=3">3</a>
        <a href="?p=4">4</a>
        </body></html>"""
        assert self.svc._parse_num_rounds(html) == 4

    def test_numberOfRounds_span_takes_priority_over_links(self):
        html = """<html><body>
        <span id="numberOfRounds">Rounds 5</span>
        <a href="?p=1">1</a>
        <a href="?p=2">2</a>
        </body></html>"""
        assert self.svc._parse_num_rounds(html) == 5

    def test_data_page_takes_priority_over_links(self):
        html = """<html><body>
        <div id="tab_pairings" data-page="6"></div>
        <a href="?p=1">1</a>
        <a href="?p=3">3</a>
        </body></html>"""
        assert self.svc._parse_num_rounds(html) == 6

    def test_default_when_no_signals(self):
        html = "<html><body></body></html>"
        assert self.svc._parse_num_rounds(html) == 4


# ── TestFetchTournament99291RealFixtures ──────────────────────────────────────


class TestFetchTournament99291RealFixtures:
    """Regression: 99291 has embedded pairings in tab_pairings and 39 players in tab_results.

    Before the fix, _parse_standings_page read tables[0] (the round-4 pairings table)
    and only collected ~20 Player-1 names instead of all 39 final standings entries.
    """

    BASE_URL = "https://aetherhub.com/Tourney/RoundTourney/99291"
    TID = "99291"

    def _html_map(self):
        fixtures_dir = Path(__file__).resolve().parents[1] / "scripts" / "aetherhub" / "fixtures"
        paths = {
            self.BASE_URL: fixtures_dir / "99291_main.html",
            f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={self.TID}&p=1": fixtures_dir
            / "99291_pairings_p1.html",
            f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={self.TID}&p=2": fixtures_dir
            / "99291_pairings_p2.html",
            f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={self.TID}&p=3": fixtures_dir
            / "99291_pairings_p3.html",
            f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={self.TID}&p=4": fixtures_dir
            / "99291_pairings_p4.html",
        }
        missing = [str(p) for url, p in paths.items() if not p.exists()]
        if missing:
            pytest.skip(f"Fixtures missing: {missing}. Run scripts/aetherhub/fetch_99291_fixtures.py")
        return {url: p.read_text(encoding="utf-8") for url, p in paths.items()}

    def test_standings_has_39_players(self):
        data = _svc(self._html_map()).fetch_tournament(self.BASE_URL)
        assert len(data.standings) == 39

    def test_standings_first_player_is_winner(self):
        data = _svc(self._html_map()).fetch_tournament(self.BASE_URL)
        assert data.standings[0] == "Федулов Ринат"

    def test_standings_last_player_is_39th(self):
        data = _svc(self._html_map()).fetch_tournament(self.BASE_URL)
        assert data.standings[-1] == "Нагорнов Владимир"

    def test_fetches_4_rounds(self):
        data = _svc(self._html_map()).fetch_tournament(self.BASE_URL)
        assert len(data.rounds) == 4

    def test_players_from_round1_has_39_players(self):
        data = _svc(self._html_map()).fetch_tournament(self.BASE_URL)
        assert len(data.players) == 39

    def test_no_points_in_standings(self):
        data = _svc(self._html_map()).fetch_tournament(self.BASE_URL)
        assert all("Points" not in name for name in data.standings)


# ── TestImportWithFinalStandingsFrom99291 ─────────────────────────────────────


class TestImportWithFinalStandingsFrom99291:
    """Part 4: import_tournament assigns final_place from standings (99291 scenario)."""

    def _participant(self, db, tournament_id, user_id):
        return db.execute(
            select(models.Participant).where(
                models.Participant.tournament_id == tournament_id,
                models.Participant.user_id == user_id,
            )
        ).scalar_one_or_none()

    def test_winner_gets_place_1_from_standings(self, import_svc, db, tournament, user_alice, user_bob):
        # Simulate 99291-style: standings in correct rank order (Bob won, Alice 2nd)
        data = _make_data(
            players=["Bob", "Alice"],
            rounds_pairings=[[("Bob", "Alice"), ("Alice", "Bob")]],
            standings=["Bob", "Alice"],
        )
        import_svc.import_tournament(tournament.id, data)
        bob = self._participant(db, tournament.id, user_bob.id)
        alice = self._participant(db, tournament.id, user_alice.id)
        assert bob.final_place == 1
        assert alice.final_place == 2

    def test_multiple_players_get_correct_places(self, import_svc, db, tournament, user_alice, user_bob):
        UserService(db).get_or_create(tg_id=9901, username=None, first_name="Юдин", last_name="Антон")
        data = _make_data(
            players=["Федулов Ринат", "Рябинин Андрей", "Юдин Антон"],
            rounds_pairings=[[("Федулов Ринат", "Рябинин Андрей"), ("Рябинин Андрей", "Федулов Ринат")]],
            standings=["Федулов Ринат", "Рябинин Андрей", "Юдин Антон"],
        )
        import_svc.import_tournament(tournament.id, data)
        anton = UserService(db).find_by_name("Юдин Антон") or UserService(db).find_by_name("Антон Юдин")
        if anton:
            p = self._participant(db, tournament.id, anton.id)
            assert p is not None
            assert p.final_place == 3


# ── TestHasPairings ───────────────────────────────────────────────────────────


class TestHasPairings:
    def test_returns_false_when_no_pairings(self, import_svc, tournament):
        assert import_svc.has_pairings(tournament.id) is False

    def test_returns_true_after_import(self, import_svc, tournament):
        data = _make_data(
            players=["Алиса", "Боб"],
            rounds_pairings=[[("Алиса", "Боб"), ("Боб", "Алиса")]],
        )
        import_svc.import_tournament(tournament.id, data)
        assert import_svc.has_pairings(tournament.id) is True

    def test_returns_false_for_other_tournament(self, import_svc, tournament, svc):
        data = _make_data(
            players=["Алиса"],
            rounds_pairings=[[("Алиса", None)]],
        )
        import_svc.import_tournament(tournament.id, data)
        other = svc.create_tournament(TournamentCreate(title="Other", chat_id=999))
        assert import_svc.has_pairings(other.id) is False


# ── TestGetPlayerOpponents ────────────────────────────────────────────────────


class TestGetPlayerOpponents:
    def _import_4player(self, import_svc, tournament):
        data = _make_data(
            players=["Иван Петров", "Алексей Боронко", "Ринат Федулов", "Андрей Рябинин"],
            rounds_pairings=[
                [
                    ("Иван Петров", "Алексей Боронко"),
                    ("Алексей Боронко", "Иван Петров"),
                    ("Ринат Федулов", "Андрей Рябинин"),
                    ("Андрей Рябинин", "Ринат Федулов"),
                ],
                [
                    ("Иван Петров", "Ринат Федулов"),
                    ("Ринат Федулов", "Иван Петров"),
                    ("Алексей Боронко", "Андрей Рябинин"),
                    ("Андрей Рябинин", "Алексей Боронко"),
                ],
            ],
            standings=["Иван Петров", "Алексей Боронко", "Ринат Федулов", "Андрей Рябинин"],
        )
        import_svc.import_tournament(tournament.id, data)

    def _participant_for_name(self, import_svc, tournament_id, name):
        user = import_svc.find_user_by_name(name)
        assert user is not None, f"User not found for name {name!r}"
        return import_svc._get_participant(tournament_id, user.id)

    def test_no_pairings_returns_error(self, import_svc, tournament):
        opps, err = import_svc.get_player_opponents(tournament.id, 9999)
        assert err == "no_pairings"
        assert opps == []

    def test_unknown_participant_returns_error(self, import_svc, tournament):
        self._import_4player(import_svc, tournament)
        opps, err = import_svc.get_player_opponents(tournament.id, 99999)
        assert err == "not_found"
        assert opps == []

    def test_returns_opponents_in_round_order(self, import_svc, tournament):
        self._import_4player(import_svc, tournament)
        p = self._participant_for_name(import_svc, tournament.id, "Иван Петров")
        opps, err = import_svc.get_player_opponents(tournament.id, p.id)
        assert err is None
        assert len(opps) == 2
        assert opps[0].round_number == 1
        assert opps[1].round_number == 2

    def test_opponent_names_correct(self, import_svc, tournament):
        self._import_4player(import_svc, tournament)
        p = self._participant_for_name(import_svc, tournament.id, "Иван Петров")
        opps, _ = import_svc.get_player_opponents(tournament.id, p.id)
        opp_names = {o.opponent_name for o in opps}
        assert "Алексей Боронко" in opp_names
        assert "Ринат Федулов" in opp_names

    def test_opponent_user_resolved(self, import_svc, tournament):
        self._import_4player(import_svc, tournament)
        p = self._participant_for_name(import_svc, tournament.id, "Иван Петров")
        opps, _ = import_svc.get_player_opponents(tournament.id, p.id)
        assert all(o.opponent_user is not None for o in opps)

    def test_opponent_participant_resolved(self, import_svc, tournament):
        self._import_4player(import_svc, tournament)
        p = self._participant_for_name(import_svc, tournament.id, "Иван Петров")
        opps, _ = import_svc.get_player_opponents(tournament.id, p.id)
        assert all(o.opponent_participant is not None for o in opps)

    def test_bye_represented_as_none_name(self, import_svc, tournament):
        data = _make_data(
            players=["Иван Петров"],
            rounds_pairings=[[("Иван Петров", None)]],
        )
        import_svc.import_tournament(tournament.id, data)
        p = self._participant_for_name(import_svc, tournament.id, "Иван Петров")
        opps, err = import_svc.get_player_opponents(tournament.id, p.id)
        assert err is None
        assert len(opps) == 1
        assert opps[0].opponent_name is None
        assert opps[0].opponent_user is None

    def test_not_in_pairings_returns_error(self, import_svc, tournament, db):
        data = _make_data(
            players=["Иван Петров"],
            rounds_pairings=[[("Иван Петров", None)]],
        )
        import_svc.import_tournament(tournament.id, data)
        stranger = UserService(db).get_or_create(tg_id=7777, username=None, first_name="Странник")
        db.add(Participant(tournament_id=tournament.id, user_id=stranger.id))
        db.commit()
        stranger_p = import_svc._get_participant(tournament.id, stranger.id)
        opps, err = import_svc.get_player_opponents(tournament.id, stranger_p.id)
        assert err == "not_in_pairings"
        assert opps == []


# ── TestFetchScoresFromMainPage ──────────────────────────────────────────────


class TestFetchScoresFromMainPage:
    """The bot service reads match scores from the main page ?p=N matchList."""

    BASE = "https://aetherhub.com/Tourney/RoundTourney/5"

    def _main(self):
        return (
            '<html><body><span id="numberOfRounds">Rounds 1</span>'
            '<table id="matchList"><tr><th>Rank</th><th>Name</th></tr>'
            "<tr><td>1</td><td>Alice</td></tr><tr><td>2</td><td>Bob</td></tr></table>"
            '<a href="?p=1">1</a></body></html>'
        )

    def _round_with_results(self):
        return (
            '<html><body><table id="matchList">'
            "<tr><th>Table</th><th>Player 1</th><th>Player 2</th><th>Match Results</th></tr>"
            "<tr><td>1</td><td>Alice (0 Points)</td><td>Bob (0 Points)</td><td>2 - 1</td></tr>"
            "</table></body></html>"
        )

    def test_scores_captured(self):
        html = {self.BASE: self._main(), f"{self.BASE}?p=1": self._round_with_results()}
        data = _svc(html).fetch_tournament(self.BASE)
        alice = next(p for p in data.rounds[0].pairings if p.player == "Alice")
        bob = next(p for p in data.rounds[0].pairings if p.player == "Bob")
        assert (alice.player_wins, alice.opponent_wins) == (2, 1)
        assert (bob.player_wins, bob.opponent_wins) == (1, 2)

    def test_falls_back_when_main_page_has_no_pairings(self):
        # main ?p=1 empty → fall back to public pairings endpoint (no scores)
        public = "https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id=5&p=1"
        html = {
            self.BASE: self._main(),
            f"{self.BASE}?p=1": "<html><body></body></html>",
            public: (
                '<html><body><table id="matchList">'
                "<tr><th>Table</th><th>P1</th><th>P2</th><th></th></tr>"
                "<tr><td>1</td><td>Alice</td><td>Bob</td><td></td></tr></table></body></html>"
            ),
        }
        data = _svc(html).fetch_tournament(self.BASE)
        alice = next(p for p in data.rounds[0].pairings if p.player == "Alice")
        assert alice.player_wins is None and alice.opponent_wins is None
        assert alice.opponent == "Bob"


# ── TestTableNumber ──────────────────────────────────────────────────────────


class TestTableNumber:
    svc = AetherhubService()

    def test_extract_plain_integer(self):
        assert self.svc._extract_table_number("12") == 12

    def test_extract_embedded_digits(self):
        assert self.svc._extract_table_number("Table 7") == 7

    def test_extract_no_digits(self):
        assert self.svc._extract_table_number("—") is None

    def test_extract_empty(self):
        assert self.svc._extract_table_number("") is None

    def test_pairings_carry_table_number(self):
        pairings = self.svc._parse_pairings_page(PAIRINGS_R1_HTML)
        alice = next(p for p in pairings if p.player == "Alice")
        carol = next(p for p in pairings if p.player == "Carol")
        assert alice.table_number == 1  # row 1: Table 1
        assert carol.table_number == 2  # row 2: Table 2 (bye)


# ── Regression: standings table must NOT be parsed as pairings ────────────────
#
# Bug: switching to the main page ?p=N for scores. On js-format tournaments the
# main page has a STANDINGS table ([Rank, Name, Points, Results, …]) and NO
# matchList. The old tables[0] fallback read it as pairings — the Points column
# ("3") became the opponent name, producing a phantom player "3"/"0" paired with
# everyone → UniqueViolation on import. Why tests missed it: every pairings
# fixture had ONLY a matchList (or a single pairings table); none reproduced a
# main page that is standings-only.


class TestStandingsNotParsedAsPairings:
    svc = AetherhubService()

    _STANDINGS_ONLY = (
        "<html><body><table>"
        "<tr><th>Rank</th><th>Name</th><th>Points</th><th>Results</th></tr>"
        "<tr><td>1</td><td>Князев Иван</td><td>3</td><td>1 - 0</td></tr>"
        "<tr><td>2</td><td>Рябинин Андрей</td><td>3</td><td>1 - 0</td></tr>"
        "</table></body></html>"
    )

    def test_parse_pairings_ignores_standings_table(self):
        # no matchList → not a pairings page → empty (no phantom "3" opponent)
        assert self.svc._parse_pairings_page(self._STANDINGS_ONLY) == []

    def test_fetch_falls_back_to_public_when_main_is_standings_only(self):
        base = "https://aetherhub.com/Tourney/RoundTourney/9"
        main = (
            '<html><body><span id="numberOfRounds">Rounds 1</span>'
            "<table><tr><th>Rank</th><th>Name</th></tr>"
            "<tr><td>1</td><td>Князев Иван</td></tr></table>"
            '<a href="?p=1">1</a></body></html>'
        )
        public = "https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id=9&p=1"
        public_html = (
            "<html><body><table id='matchList'>"
            "<tr><th>Table</th><th>Player 1</th><th>Player 2</th></tr>"
            "<tr><td>1</td><td>Князев Иван</td><td>Березин Дмитрий</td></tr>"
            "</table></body></html>"
        )
        html = {base: main, f"{base}?p=1": self._STANDINGS_ONLY, public: public_html}
        data = _svc(html).fetch_tournament(base)
        names = {p.player for p in data.rounds[0].pairings} | {
            p.opponent for p in data.rounds[0].pairings if p.opponent
        }
        assert names == {"Князев Иван", "Березин Дмитрий"}
        assert "3" not in names  # the bug: Points column became a phantom opponent
