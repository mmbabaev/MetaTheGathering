import random
from pathlib import Path

import pytest

from pauper_sim.logic import MATCH_GAMES, Player, pair_players, roll_game, win_probability
from pauper_sim.winrates import parse_winrates

FIXTURES = Path(__file__).parent / "fixtures"
WEBRATES = parse_winrates((FIXTURES / "winrates.html").read_text(encoding="utf-8"), fetched_at=1.0)


class FakeRng:
    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


def test_match_games_first_to_two() -> None:
    assert MATCH_GAMES == 2


def test_both_matchup_directions_averaged() -> None:
    assert win_probability("Mono Red Madness", "Grixis Affinity", WEBRATES) == 43.0
    assert win_probability("Mono Blue Terror", "Mono Red Madness", WEBRATES) == 63.0


def test_single_direction_matchup() -> None:
    assert win_probability("Mono Red Burn", "Mono Red Madness", WEBRATES) == 45.0


def test_fallback_to_overall_winrates() -> None:
    burn = next(deck for deck in WEBRATES.decks if deck.name == "Mono Red Burn")
    jund = next(deck for deck in WEBRATES.decks if deck.name == "Jund Wildfire")
    expected = burn.overall_winrate * 100.0 / (burn.overall_winrate + jund.overall_winrate)
    assert win_probability("Mono Red Burn", "Jund Wildfire", WEBRATES) == pytest.approx(expected)


def test_unknown_deck_even() -> None:
    assert win_probability("Unknown Deck", "Elves", WEBRATES) == 50.0


def test_roll_game_weighted_low_roll_wins_for_underdog() -> None:
    assert roll_game("Mono Red Madness", "Grixis Affinity", WEBRATES, FakeRng(0.01)) == "a"
    assert roll_game("Mono Red Madness", "Grixis Affinity", WEBRATES, FakeRng(0.99)) == "b"


def test_roll_game_boundary_at_winrate_threshold() -> None:
    assert roll_game("Mono Red Madness", "Grixis Affinity", WEBRATES, FakeRng(0.4299)) == "a"
    assert roll_game("Mono Red Madness", "Grixis Affinity", WEBRATES, FakeRng(0.4301)) == "b"


def test_pair_players_even_pairs_bottom_up() -> None:
    players = [Player(name=f"P{i}", deck="Deck") for i in range(4)]
    shuffled = list(players)
    random.Random(7).shuffle(shuffled)

    matches, bye = pair_players(players, random.Random(7))
    assert bye is None
    assert matches == [
        (shuffled[2], shuffled[3]),
        (shuffled[0], shuffled[1]),
    ]
    covered = {player.name for pair in matches for player in pair}
    assert covered == {player.name for player in players}


def test_pair_players_odd_top_of_shuffle_gets_bye() -> None:
    players = [Player(name=f"P{i}", deck="Deck") for i in range(5)]
    shuffled = list(players)
    random.Random(7).shuffle(shuffled)

    matches, bye = pair_players(players, random.Random(7))
    assert bye == shuffled[0]
    assert matches == [
        (shuffled[3], shuffled[4]),
        (shuffled[1], shuffled[2]),
    ]
    covered = {player.name for pair in matches for player in pair}
    assert covered | {bye.name} == {player.name for player in players}
