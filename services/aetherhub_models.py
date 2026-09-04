"""Data models for Aetherhub tournament parsing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class AetherhubPairing:
    player: str
    opponent: str | None  # None = bye
    table_number: int | None = None  # номер стола (пары); None = неизвестно
    player_wins: int | None = None  # победы игрока в матче; None = счёт неизвестен
    opponent_wins: int | None = None  # победы соперника в матче; None = счёт неизвестен


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
    # Паупер ли турнир: определяется по всему тексту ячейки (имя + формат-подзаголовок).
    # У Goldfish имя — просто дата, а «Pauper» стоит в подзаголовке «Constructed: Pauper Tourney»;
    # у Edinorog формат («Паупер»/«Легаси»/…) стоит в имени. Поиск по тексту ячейки ловит оба.
    is_pauper: bool = False
    # AetherHub иногда теряет формат и показывает только нейтральный «Constructed Tourney».
    # Такой турнир можно брать лишь через строгий fallback по точной дате и имени-дате.
    is_generic_constructed: bool = False
