from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

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


@dataclass
class ClubTournamentLink:
    name: str
    url: str
    date: date | None


PAUPER_RE = re.compile(r"pauper|пупер", re.IGNORECASE)

_DATE_FORMATS = [
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "%Y-%m-%d"),
    (re.compile(r"\d{2}\.\d{2}\.\d{4}"), "%d.%m.%Y"),
    (re.compile(r"\d{1,2}/\d{1,2}/\d{4}"), "%m/%d/%Y"),
    (re.compile(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4}", re.IGNORECASE), None),
]

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _extract_date(text: str) -> date | None:
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
        else:
            # Flexible month-name format: "Apr 21, 2026" / "April 21 2026"
            parts = re.split(r"[\s,]+", raw)
            if len(parts) >= 3:
                try:
                    month = _MONTH_MAP.get(parts[0][:3].lower())
                    day = int(parts[1])
                    year = int(parts[2])
                    if month:
                        return date(year, month, day)
                except (ValueError, IndexError):
                    continue
    return None


def _parse_club_page(html: str) -> list[ClubTournamentLink]:
    """Parse AetherHub club page HTML; return list of tournament links."""
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

        # Look for a date in the link text or the parent row/cell
        row = a.find_parent("tr") or a.find_parent("li") or a.parent
        context_text = row.get_text(" ", strip=True) if row else name
        tournament_date = _extract_date(context_text) or _extract_date(name)

        results.append(ClubTournamentLink(name=name, url=url, date=tournament_date))

    return results


def fetch_club_tournaments(club_url: str) -> list[ClubTournamentLink]:
    """Fetch the AetherHub club/user page and return all tournament links."""
    html = _scraper().get(club_url, timeout=30).text
    return _parse_club_page(html)


def find_todays_pauper_tournament(club_url: str, today: date | None = None) -> str | None:
    """Return the URL of today's pauper tournament from a club page, or None."""
    if today is None:
        today = date.today()
    for link in fetch_club_tournaments(club_url):
        if link.date == today and PAUPER_RE.search(link.name):
            return link.url
    return None


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
