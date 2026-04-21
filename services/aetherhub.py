from __future__ import annotations

import re
from dataclasses import dataclass, field

import cloudscraper
from bs4 import BeautifulSoup


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
    players: list[str]           # from round 1 standings
    rounds: list[AetherhubRound]


def _strip_points(name: str) -> str:
    return re.sub(r"\s*\(\d+ Points?\)\s*$", "", name).strip()


def _scraper():
    return cloudscraper.create_scraper()


def _parse_page(html: str) -> tuple[list[str], list[AetherhubPairing], int]:
    """Returns (player_names_from_standings, pairings, max_round_found)."""
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    pairings: list[AetherhubPairing] = []
    if len(tables) >= 1:
        for row in tables[0].find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 3:
                continue
            p1 = _strip_points(cells[1])
            p2 = _strip_points(cells[2]) if cells[2] else None
            if p1:
                pairings.append(AetherhubPairing(player=p1, opponent=p2 or None))
            if p2:
                pairings.append(AetherhubPairing(player=p2, opponent=p1 or None))

    players: list[str] = []
    if len(tables) >= 2:
        for row in tables[1].find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) >= 2 and cells[1]:
                players.append(cells[1].strip())

    # Detect max round number from nav links (?p=N)
    max_round = 1
    for a in soup.find_all("a", href=True):
        m = re.search(r"\?p=(\d+)", a["href"])
        if m:
            max_round = max(max_round, int(m.group(1)))

    return players, pairings, max_round


def fetch_tournament(url: str) -> AetherhubTournamentData:
    """Fetch aetherhub tournament: players from round 1, pairings from all rounds."""
    scraper = _scraper()

    # Round 1: get player list + round 1 pairings
    r1_html = scraper.get(f"{url}?p=1", timeout=30).text
    players, r1_pairings, max_round = _parse_page(r1_html)

    rounds = [AetherhubRound(number=1, pairings=r1_pairings)]

    for rn in range(2, max_round + 1):
        html = scraper.get(f"{url}?p={rn}", timeout=30).text
        _, pairings, _ = _parse_page(html)
        rounds.append(AetherhubRound(number=rn, pairings=pairings))

    return AetherhubTournamentData(url=url, players=players, rounds=rounds)
