"""Data models for Aetherhub tournament parsing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class AetherhubPairing:
    player: str
    opponent: str | None  # None = bye


@dataclass
class AetherhubRound:
    number: int
    pairings: list[AetherhubPairing]


@dataclass
class AetherhubTournamentData:
    url: str
    players: list[str]  # all players for registration (from round 1 pairings)
    rounds: list[AetherhubRound]
    standings: list[str] = None  # players ordered by final place (1st → last); empty = not available

    def __post_init__(self):
        if self.standings is None:
            self.standings = []


@dataclass
class ClubTournamentLink:
    name: str
    url: str
    date: date | None
