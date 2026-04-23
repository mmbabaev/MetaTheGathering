"""Data models for Aetherhub tournament parsing."""

from dataclasses import dataclass


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
    players: list[str]  # from round 1 standings
    rounds: list[AetherhubRound]
