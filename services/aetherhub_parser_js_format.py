"""Parser for Aetherhub tournaments with JavaScript-loaded pairings (Format 2)."""

import re
from typing import Optional

import cloudscraper
from bs4 import BeautifulSoup

from services.aetherhub_models import (
    AetherhubPairing,
    AetherhubRound,
    AetherhubTournamentData,
)


class AetherhubJSFormatParser:
    """
    Parser for Aetherhub tournaments where pairings are loaded dynamically via JavaScript.

    This format is identified by having an empty pairings tab in the main HTML,
    with pairings loaded via the API endpoint:
    /Tourney/RoundTourneyPublicPairings?id={tournament_id}&round={round_num}

    Example: https://aetherhub.com/Tourney/RoundTourney/99024
    """

    PAIRINGS_ENDPOINT = "/Tourney/RoundTourneyPublicPairings"

    def __init__(self, scraper: Optional[cloudscraper.CloudScraper] = None):
        """Initialize parser with optional cloudscraper instance."""
        self.scraper = scraper or cloudscraper.create_scraper()

    def parse_tournament(self, url: str) -> AetherhubTournamentData:
        """
        Parse a complete tournament from Aetherhub.

        Args:
            url: Tournament URL (e.g., https://aetherhub.com/Tourney/RoundTourney/99024)

        Returns:
            AetherhubTournamentData with players and all round pairings

        Raises:
            ValueError: If tournament ID cannot be extracted or data is invalid
            requests.RequestException: If network request fails
        """
        tournament_id = self._extract_tournament_id(url)

        # Fetch main page
        resp = self.scraper.get(url, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Extract players from standings
        players = self._parse_players(soup)

        # Extract number of rounds
        num_rounds = self._parse_num_rounds(soup)

        # Fetch pairings for each round
        rounds = []
        for round_num in range(1, num_rounds + 1):
            round_data = self._parse_round(tournament_id, round_num)
            if round_data:
                rounds.append(round_data)

        return AetherhubTournamentData(
            url=url,
            players=players,
            rounds=rounds,
        )

    def _extract_tournament_id(self, url: str) -> str:
        """Extract tournament ID from URL."""
        # URL format: https://aetherhub.com/Tourney/RoundTourney/99024
        match = re.search(r"/RoundTourney/(\d+)", url)
        if not match:
            raise ValueError(f"Cannot extract tournament ID from URL: {url}")
        return match.group(1)

    def _parse_players(self, soup: BeautifulSoup) -> list[str]:
        """Extract player list from standings table."""
        players = []

        # Find the standings table (first table on page)
        table = soup.find("table")
        if not table:
            return players

        # Skip header row, iterate through player rows
        rows = table.find_all("tr")[1:]
        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 2:
                name_cell = cells[1]
                link = name_cell.find("a")
                if link:
                    player_name = link.text.strip()
                    if player_name:
                        players.append(player_name)

        return players

    def _parse_num_rounds(self, soup: BeautifulSoup) -> int:
        """Extract the number of rounds in the tournament."""
        # Try to find numberOfRounds span
        num_rounds_elem = soup.find("span", {"id": "numberOfRounds"})
        if num_rounds_elem:
            # Format: "Rounds 4"
            text = num_rounds_elem.text.strip()
            match = re.search(r"\d+", text)
            if match:
                return int(match.group())

        # Fallback: check data-page attribute on pairings tab
        pairings_tab = soup.find("div", {"id": "tab_pairings"})
        if pairings_tab and pairings_tab.get("data-page"):
            return int(pairings_tab["data-page"])

        # Default: assume 4 rounds
        return 4

    def _parse_round(self, tournament_id: str, round_num: int) -> Optional[AetherhubRound]:
        """
        Fetch and parse pairings for a specific round.

        Args:
            tournament_id: Tournament ID
            round_num: Round number (1-indexed)

        Returns:
            AetherhubRound if successful, None if failed
        """
        url = f"https://aetherhub.com{self.PAIRINGS_ENDPOINT}?id={tournament_id}&round={round_num}"

        try:
            resp = self.scraper.get(url, timeout=30)
            resp.raise_for_status()
        except Exception:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"id": "matchList"})

        if not table:
            return None

        tbody = table.find("tbody")
        if not tbody:
            return None

        pairings = []
        rows = tbody.find_all("tr")

        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 3:
                # Column 0: Table number
                # Column 1: Player 1
                # Column 2: Player 2

                player1_text = cells[1].get_text(strip=True)
                player2_text = cells[2].get_text(strip=True)

                # Extract name (remove points in parentheses)
                # Format: "Старостин Владислав (9 Points)"
                player1_name = self._extract_player_name(player1_text)
                player2_name = self._extract_player_name(player2_text) if player2_text else None

                if player1_name:
                    # Add pairing for player1
                    pairings.append(AetherhubPairing(player=player1_name, opponent=player2_name))

                    # If not a bye, add reverse pairing for player2
                    if player2_name:
                        pairings.append(AetherhubPairing(player=player2_name, opponent=player1_name))

        return AetherhubRound(
            number=round_num,
            pairings=pairings,
        )

    def _extract_player_name(self, text: str) -> Optional[str]:
        """
        Extract player name from text like 'Name (9 Points)'.

        Args:
            text: Raw text from table cell

        Returns:
            Clean player name or None if empty
        """
        if not text:
            return None

        # Remove points in parentheses
        name = text.split("(")[0].strip()

        return name if name else None
