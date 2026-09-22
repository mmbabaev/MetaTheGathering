"""Pure matchup math for the Pauper Duel Simulator.

Win probability uses the pairwise head-to-head winrates from mtgdecks.net when
available (both directions are averaged for symmetry) and falls back to the
normalised overall winrates otherwise.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from pauper_sim.winrates import WinrateData

MATCH_GAMES = 2


@dataclass(frozen=True)
class Player:
    name: str
    deck: str


def _overall_map(data: WinrateData) -> dict[str, float]:
    return {deck.name: deck.overall_winrate for deck in data.decks}


def win_probability(deck: str, opponent: str, data: WinrateData) -> float:
    """Winrate (percent) of `deck` in a match against `opponent`."""
    direct = data.winrate_against(deck, opponent)
    reverse = data.winrate_against(opponent, deck)
    if direct is not None and reverse is not None:
        return (direct + (100 - reverse)) / 2.0
    if direct is not None:
        return float(direct)
    if reverse is not None:
        return 100.0 - reverse

    overall = _overall_map(data)
    wa = overall.get(deck)
    wb = overall.get(opponent)
    if not wa or not wb:
        return 50.0
    return wa * 100.0 / (wa + wb)


def roll_game(deck_a: str, deck_b: str, data: WinrateData, rng: random.Random) -> str:
    """Return 'a' or 'b' — the deck that wins one game, weighted by winrates."""
    probability = win_probability(deck_a, deck_b, data)
    return "a" if rng.random() * 100.0 < probability else "b"


def pair_players(players: list[Player], rng: random.Random) -> tuple[list[tuple[Player, Player]], Player | None]:
    """Randomly shuffle the players and pair them from the bottom of the list up.

    Returns (ordered matches, bye). With an odd number of players the player at
    the top of the shuffled list gets a bye and everyone else plays.
    """
    shuffled = list(players)
    rng.shuffle(shuffled)
    bye: Player | None = None
    if len(shuffled) % 2 == 1:
        bye = shuffled[0]
        shuffled = shuffled[1:]
    matches = [(shuffled[i - 1], shuffled[i]) for i in range(len(shuffled) - 1, 0, -2)]
    return matches, bye
