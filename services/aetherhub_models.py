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
    players: list[str]  # from round 1 standings
    rounds: list[AetherhubRound]


@dataclass
class ClubTournamentLink:
    name: str
    url: str
    date: date | None
