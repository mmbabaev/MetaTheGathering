from __future__ import annotations

import re
from datetime import date, datetime

import cloudscraper
from bs4 import BeautifulSoup

from services.aetherhub_models import (
    AetherhubPairing,
    AetherhubRound,
    AetherhubTournamentData,
    ClubTournamentLink,
)

PAUPER_RE = re.compile(r"pauper|пупер", re.IGNORECASE)

_DATE_FORMATS = [
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "%Y-%m-%d"),
    (re.compile(r"\d{2}\.\d{2}\.\d{4}"), "%d.%m.%Y"),
    (re.compile(r"\d{1,2}/\d{1,2}/\d{4}"), "%m/%d/%Y"),
    (re.compile(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4}", re.IGNORECASE), None),
]

_MONTH_MAP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


class AetherhubService:
    def __init__(self, scraper=None):
        self._scraper = scraper or cloudscraper.create_scraper()

    def _strip_points(self, name: str) -> str:
        return re.sub(r"\s*\(\d+ Points?\)\s*$", "", name).strip()

    def _players_from_pairings(self, pairings: list[AetherhubPairing]) -> list[str]:
        names = [p.player for p in pairings] + [p.opponent for p in pairings if p.opponent]
        return list(dict.fromkeys(names))

    def _parse_page(self, html: str) -> tuple[list[str], list[AetherhubPairing], int]:
        """Returns (player_names_from_standings, pairings, max_round_found)."""
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

        max_round = 1
        for a in soup.find_all("a", href=True):
            m = re.search(r"\?p=(\d+)", a["href"])
            if m:
                max_round = max(max_round, int(m.group(1)))

        return players, pairings, max_round

    def _extract_date(self, text: str) -> date | None:
        for pattern, fmt in _DATE_FORMATS:
            m = pattern.search(text)
            if not m:
                continue
            raw = m.group()
            if fmt:
                try:
                    return datetime.strptime(raw, fmt).date()
                except ValueError:
                    continue
            parts = re.split(r"[\s,]+", raw)
            if len(parts) < 3:
                continue
            try:
                month = _MONTH_MAP.get(parts[0][:3].lower())
                day, year = int(parts[1]), int(parts[2])
                if month:
                    return date(year, month, day)
            except (ValueError, IndexError):
                continue
        return None

    def _parse_club_page(self, html: str) -> list[ClubTournamentLink]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[ClubTournamentLink] = []
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            if "/Tourney/" not in href:
                continue
            url = href if href.startswith("http") else f"https://aetherhub.com{href}"
            if url in seen:
                continue
            seen.add(url)

            name = a.get_text(strip=True)
            if not name:
                continue

            row = a.find_parent("tr") or a.find_parent("li") or a.parent
            context_text = row.get_text(" ", strip=True) if row else name
            tournament_date = self._extract_date(context_text) or self._extract_date(name)

            results.append(ClubTournamentLink(name=name, url=url, date=tournament_date))

        return results

    def fetch_club_tournaments(self, club_url: str, today: date | None = None) -> list[ClubTournamentLink]:
        html = self._scraper.get(club_url, timeout=30).text
        return self._parse_club_page(html)

    def find_todays_pauper_tournament(self, club_url: str, today: date | None = None) -> str | None:
        for link in self.fetch_club_tournaments(club_url, today=today):
            if (today is None or link.date == today) and PAUPER_RE.search(link.name):
                return link.url
        return None

    def fetch_tournament(self, url: str) -> AetherhubTournamentData:
        r1_html = self._scraper.get(f"{url}?p=1", timeout=30).text
        players, r1_pairings, max_round = self._parse_page(r1_html)
        if not players:
            players = self._players_from_pairings(r1_pairings)

        rounds = [AetherhubRound(number=1, pairings=r1_pairings)]

        for rn in range(2, max_round + 1):
            html = self._scraper.get(f"{url}?p={rn}", timeout=30).text
            _, pairings, _ = self._parse_page(html)
            rounds.append(AetherhubRound(number=rn, pairings=pairings))

        return AetherhubTournamentData(url=url, players=players, rounds=rounds)
