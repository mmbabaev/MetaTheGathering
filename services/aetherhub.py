from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

import cloudscraper
from bs4 import BeautifulSoup

from services.aetherhub_models import (
    AetherhubPairing,
    AetherhubRound,
    AetherhubTournamentData,
)
from services.aetherhub_parser_edinorog import AetherhubEdinorogParser
from services.aetherhub_parser_js_format import AetherhubJSFormatParser

# Re-export models for backward compatibility
__all__ = [
    "AetherhubTournamentData",
    "AetherhubRound",
    "AetherhubPairing",
    "fetch_tournament",
    "fetch_club_tournaments",
    "find_todays_pauper_tournament",
    "ClubTournamentLink",
]


def _scraper():
    return cloudscraper.create_scraper()


# Backward compatibility: re-export internal functions used by tests
def _strip_points(name: str) -> str:
    """Remove points suffix from player name (backward compatibility)."""
    parser = AetherhubEdinorogParser()
    return parser._strip_points(name)


def _parse_page(html: str) -> tuple[list[str], list[AetherhubPairing], int]:
    """Parse edinorog format page (backward compatibility)."""
    parser = AetherhubEdinorogParser()
    return parser._parse_page(html)


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
    """Return the URL of a pauper tournament from a club page.

    If today is given, matches only that date.
    If today is None, returns the first (latest) pauper tournament found regardless of date.
    """
    for link in fetch_club_tournaments(club_url):
        if PAUPER_RE.search(link.name):
            if today is None or link.date == today:
                return link.url
    return None


def _detect_tournament_format(html: str) -> str:
    """
    Detect tournament format from HTML.

    Returns:
        "js" for JavaScript-loaded format (Format 2)
        "edinorog" for embedded HTML format (Format 1)
    """
    soup = BeautifulSoup(html, "html.parser")

    # Check if pairings tab exists and is empty (JS format indicator)
    pairings_tab = soup.find("div", {"id": "tab_pairings"})
    if pairings_tab is not None:
        # JS format has empty pairings tab with data-page attribute
        has_data_page = pairings_tab.get("data-page") is not None
        is_empty = len(pairings_tab.find_all("table")) == 0

        if has_data_page and is_empty:
            return "js"

    # Default to edinorog format
    return "edinorog"


def fetch_tournament(url: str) -> AetherhubTournamentData:
    """
    Fetch aetherhub tournament: players from round 1, pairings from all rounds.

    Automatically detects the tournament format and uses the appropriate parser:
    - Format 1 (edinorog): Uses ?p=X URL parameters, pairings embedded in HTML
    - Format 2 (JS): Uses /Tourney/RoundTourneyPublicPairings API endpoint

    Args:
        url: Tournament URL (query parameters will be stripped)

    Returns:
        AetherhubTournamentData with players and all round pairings
    """
    # Strip query parameters from URL
    if "?" in url:
        url = url.split("?")[0]

    scraper = _scraper()

    # Fetch main page to detect format
    main_html = scraper.get(url, timeout=30).text
    format_type = _detect_tournament_format(main_html)

    # Use appropriate parser
    if format_type == "js":
        parser = AetherhubJSFormatParser(scraper=scraper)
        return parser.parse_tournament(url)
    else:  # edinorog
        parser = AetherhubEdinorogParser(scraper=scraper)
        return parser.parse_tournament(url)
