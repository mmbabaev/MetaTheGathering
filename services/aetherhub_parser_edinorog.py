"""Parser for Aetherhub tournaments with edinorog format (Format 1)."""

import re
from typing import Optional

import cloudscraper
from bs4 import BeautifulSoup

from services.aetherhub_models import (
    AetherhubPairing,
    AetherhubRound,
    AetherhubTournamentData,
)


class AetherhubEdinorogParser:
    """
    Parser for Aetherhub tournaments where pairings are embedded in HTML.

    This format uses URL parameters (?p=N) to navigate between rounds,
    with pairings visible directly in the HTML tables.

    Example: https://aetherhub.com/Tourney/RoundTourney/98984
    """

    def __init__(self, scraper: Optional[cloudscraper.CloudScraper] = None):
        """Initialize parser with optional cloudscraper instance."""
        self.scraper = scraper or cloudscraper.create_scraper()

    def parse_tournament(self, url: str) -> AetherhubTournamentData:
        """
        Parse a complete tournament from Aetherhub (edinorog format).

        Args:
            url: Tournament URL (e.g., https://aetherhub.com/Tourney/RoundTourney/98984)

        Returns:
            AetherhubTournamentData with players and all round pairings
        """
        # Round 1: get player list + round 1 pairings
        r1_html = self.scraper.get(f"{url}?p=1", timeout=30).text
        players, r1_pairings, max_round = self._parse_page(r1_html)

        rounds = [AetherhubRound(number=1, pairings=r1_pairings)]

        for rn in range(2, max_round + 1):
            html = self.scraper.get(f"{url}?p={rn}", timeout=30).text
            _, pairings, _ = self._parse_page(html)
            rounds.append(AetherhubRound(number=rn, pairings=pairings))

        return AetherhubTournamentData(url=url, players=players, rounds=rounds)

    def _parse_page(self, html: str) -> tuple[list[str], list[AetherhubPairing], int]:
        """
        Parse a page of edinorog format tournament.

        Returns:
            Tuple of (player_names_from_standings, pairings, max_round_found)
        """
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")

        pairings: list[AetherhubPairing] = []
        if len(tables) >= 1:
            for row in tables[0].find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 3:
                    continue
                p1 = self._strip_points(cells[1])
                p2 = self._strip_points(cells[2]) if cells[2] else None
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

    def _strip_points(self, name: str) -> str:
        """Remove points suffix from player name."""
        return re.sub(r"\s*\(\d+ Points?\)\s*$", "", name).strip()
