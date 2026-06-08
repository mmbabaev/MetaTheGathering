from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import cloudscraper
from bs4 import BeautifulSoup

from services.aetherhub_models import (
    AetherhubPairing,
    AetherhubRound,
    AetherhubTournamentData,
    ClubTournamentLink,
)

PAUPER_RE = re.compile(r"pauper|паупер|пупер", re.IGNORECASE)

_RESULT_RE = re.compile(r"(\d+)\s*[-–]\s*(\d+)")


def _parse_match_result(text: str) -> tuple[int | None, int | None]:
    """Счёт матча «2 - 0» → (2, 0). Пусто/нет счёта → (None, None)."""
    m = _RESULT_RE.search(text or "")
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


_DATE_FORMATS = [
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "%Y-%m-%d"),
    (re.compile(r"\d{2}\.\d{2}\.\d{4}"), "%d.%m.%Y"),
    (re.compile(r"\d{1,2}/\d{1,2}/\d{4}"), "%m/%d/%Y"),
    (re.compile(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4}", re.IGNORECASE), None),
]

# DD.MM without year — matched separately to infer year
_DAY_MONTH_RE = re.compile(r"\b(\d{1,2})\.(\d{2})\b")

_DAYS_AGO_RE = re.compile(r"(\d+)\s+days?\s+ago", re.IGNORECASE)

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
        # Aetherhub sometimes injects points inside the player label, e.g.
        # "Валентин (6 Points) Задорожний". Remove it anywhere, case-insensitive.
        s = re.sub(r"\(\s*\d+\s*points?\s*\)", "", name or "", flags=re.IGNORECASE)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _players_from_pairings(self, pairings: list[AetherhubPairing]) -> list[str]:
        names = [p.player for p in pairings] + [p.opponent for p in pairings if p.opponent]
        return list(dict.fromkeys(names))

    def _parse_num_rounds(self, html: str) -> int:
        """Best-effort extraction of number of rounds from main tournament HTML."""
        soup = BeautifulSoup(html, "html.parser")

        num_rounds_elem = soup.find("span", {"id": "numberOfRounds"})
        if num_rounds_elem:
            m = re.search(r"\d+", num_rounds_elem.get_text(strip=True))
            if m:
                return int(m.group())

        pairings_tab = soup.find("div", {"id": "tab_pairings"})
        if pairings_tab and pairings_tab.get("data-page"):
            try:
                return int(pairings_tab["data-page"])
            except (TypeError, ValueError):
                pass

        # Fallback: scan navigation links for ?p=N (edinorog format without data-page)
        max_from_links = 0
        for a in soup.find_all("a", href=True):
            m = re.search(r"\?p=(\d+)", a["href"])
            if m:
                max_from_links = max(max_from_links, int(m.group(1)))
        if max_from_links > 0:
            return max_from_links

        return 4

    @staticmethod
    def _is_bye(name: str) -> bool:
        return name.upper() == "BYE"

    def _parse_standings_page(self, html: str) -> tuple[list[str], int]:
        """Returns (player_names_from_standings, max_round_found) from the main tournament page."""
        soup = BeautifulSoup(html, "html.parser")

        # Prefer the explicit standings tab; fall back to the first table in the document.
        # Completed tournaments show round N pairings in tab_pairings (which comes first),
        # so using tab_results avoids reading the wrong table.
        standings_table = None
        tab_results = soup.find("div", {"id": "tab_results"})
        if tab_results:
            standings_table = tab_results.find("table")
        if standings_table is None:
            tables = soup.find_all("table")
            standings_table = tables[0] if tables else None

        players: list[str] = []
        if standings_table:
            for row in standings_table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) >= 2 and cells[1]:
                    name = self._strip_points(cells[1])
                    if name and not self._is_bye(name):
                        players.append(name)

        max_round = 1
        for a in soup.find_all("a", href=True):
            m = re.search(r"\?p=(\d+)", a["href"])
            if m:
                max_round = max(max_round, int(m.group(1)))

        return players, max_round

    def _parse_pairings_page(self, html: str) -> list[AetherhubPairing]:
        """Parse the matchList table (pairings + optional «Match Results» score column).

        Works for both the main tournament page (``?p=N`` — has the score column)
        and the public pairings endpoint (score column empty).
        """
        soup = BeautifulSoup(html, "html.parser")
        # ТОЛЬКО matchList. Без фолбэка на tables[0]: на js-формате главная ?p=N
        # отдаёт таблицу standings ([Rank, Name, Points, …]) — если её распарсить
        # как паринги, Points попадает в имя оппонента («3», «0»). Нет matchList →
        # это не страница парингов, возвращаем пусто (вызвавший уйдёт в фолбэк).
        table = soup.find("table", {"id": "matchList"})
        pairings: list[AetherhubPairing] = []
        if table is None:
            return pairings
        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 3:
                continue
            table_number = self._extract_table_number(cells[0])  # 1-я колонка «Table»
            p1 = self._strip_points(cells[1])
            p2_raw = self._strip_points(cells[2]) if cells[2] else None
            p2 = None if (p2_raw and self._is_bye(p2_raw)) else p2_raw
            # 4-я колонка «Match Results»: "2 - 0" (на главной странице; иначе пусто)
            w1, w2 = _parse_match_result(cells[3] if len(cells) > 3 else "")
            if p1 and not self._is_bye(p1):
                pairings.append(
                    AetherhubPairing(
                        player=p1, opponent=p2 or None, table_number=table_number, player_wins=w1, opponent_wins=w2
                    )
                )
            if p2:
                pairings.append(
                    AetherhubPairing(
                        player=p2, opponent=p1 or None, table_number=table_number, player_wins=w2, opponent_wins=w1
                    )
                )
        return pairings

    @staticmethod
    def _extract_table_number(text: str) -> int | None:
        """Номер стола из ячейки «Table» («1», «Table 7») — первое целое, иначе None."""
        m = re.search(r"\d+", text or "")
        return int(m.group()) if m else None

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
        return self._extract_day_month(text)

    def _extract_day_month(self, text: str, today: date | None = None) -> date | None:
        """Parse DD.MM without year, inferring year so the date is not in the future."""
        m = _DAY_MONTH_RE.search(text)
        if not m:
            return None
        try:
            day, month = int(m.group(1)), int(m.group(2))
            ref = today or date.today()
            candidate = date(ref.year, month, day)
            if candidate > ref + timedelta(days=1):
                candidate = date(ref.year - 1, month, day)
            return candidate
        except ValueError:
            return None

    def _extract_days_ago(self, container, today: date) -> date | None:
        if container is None:
            return None
        small = container.find("small", class_="text-muted")
        if small is None:
            return None
        m = _DAYS_AGO_RE.search(small.get_text(strip=True))
        if not m:
            return None
        return today - timedelta(days=int(m.group(1)))

    def _parse_club_page(self, html: str, today: date | None = None) -> list[ClubTournamentLink]:
        soup = BeautifulSoup(html, "html.parser")
        today = today or date.today()
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

            container = a.find_parent("div", class_="w-100") or a.find_parent("tr") or a.find_parent("li") or a.parent
            tournament_date = (
                self._extract_date(name)
                or self._extract_days_ago(container, today)
                or self._extract_date(container.get_text(" ", strip=True) if container else name)
            )

            results.append(ClubTournamentLink(name=name, url=url, date=tournament_date))

        return results

    def fetch_club_tournaments(self, club_url: str, today: date | None = None) -> list[ClubTournamentLink]:
        html = self._scraper.get(club_url, timeout=30).text
        return self._parse_club_page(html, today=today)

    def find_todays_pauper_tournament(self, club_url: str, today: date | None = None) -> str | None:
        for link in self.fetch_club_tournaments(club_url, today=today):
            if (today is None or link.date == today) and PAUPER_RE.search(link.name):
                return link.url
        return None

    def _pairings_url(self, tourney_id: str, round_num: int) -> str:
        return f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={tourney_id}&p={round_num}"

    def fetch_tournament(self, url: str) -> AetherhubTournamentData:
        # The main tournament URL can default to a later round/page depending on tournament state.
        # Always strip query params and rely on round 1 pairings for the canonical player list.
        if "?" in url:
            url = url.split("?", 1)[0]
        m = re.search(r"/(\d+)/?$", url)
        if not m:
            raise ValueError(f"Cannot extract tournament ID from URL: {url}")
        tourney_id = m.group(1)

        main_html = self._scraper.get(url, timeout=30).text
        max_round = self._parse_num_rounds(main_html)

        # `max_round` is only an upper bound: during a live event the round navigation
        # briefly exposes extra ?p=N tabs (standings/results), inflating the count.
        # AetherHub clamps an out-of-range round to the LAST real round — requesting
        # ?p=5 on a 4-round event returns round 4's pairings verbatim. Detect that by
        # comparing each round's pairing set to the previous one and stop on a repeat,
        # so phantom rounds are never stored. (Swiss never repeats a full pairing set.)
        rounds = []
        prev_signature: frozenset | None = None
        for rn in range(1, max_round + 1):
            # Главная страница ?p=N содержит matchList СО счётом («Match Results»).
            # Если там пусто (js-формат с динамической подгрузкой) — фолбэк на
            # публичный pairings-эндпоинт (паринги без счёта).
            pairings = self._parse_pairings_page(self._scraper.get(f"{url}?p={rn}", timeout=30).text)
            if not pairings:
                pairings = self._parse_pairings_page(
                    self._scraper.get(self._pairings_url(tourney_id, rn), timeout=30).text
                )
            signature = frozenset((p.player, p.opponent) for p in pairings)
            if rn > 1 and signature and signature == prev_signature:
                break  # clamped duplicate of the previous round → phantom, stop here
            rounds.append(AetherhubRound(number=rn, pairings=pairings))
            prev_signature = signature

        players = self._players_from_pairings(rounds[0].pairings) if rounds else []
        standings, _ = self._parse_standings_page(main_html)

        return AetherhubTournamentData(url=url, players=players, rounds=rounds, standings=standings)
