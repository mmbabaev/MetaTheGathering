from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

import cloudscraper
import requests
from bs4 import BeautifulSoup

from services.aetherhub_models import (
    AetherhubPairing,
    AetherhubRound,
    AetherhubTournamentData,
    ClubTournamentLink,
)

PAUPER_RE = re.compile(r"pauper|паупер|пупер", re.IGNORECASE)

# Ссылка на страницу турнира — с числовым id (отсекает навигацию: /Tourney/, /Tourney/Leagues …)
_TOURNEY_LINK_RE = re.compile(r"/Tourney/\w+/\d+")

_RESULT_RE = re.compile(r"(\d+)\s*[-–]\s*(\d+)")

_GET_ATTEMPTS = 3
_GET_RETRY_BACKOFF_SECONDS = 0.5


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

# DD.MM / DD/MM without year — matched separately to infer year.
# Слэш обязателен: организаторы пишут дату и через точку («16.07»), и через слэш («16/07»);
# без слэша дата из имени не читалась и код падал на хрупкий «N days ago».
_DAY_MONTH_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})\b")

# «Сколько назад создан» внизу ячейки клуба: «4 hours ago», «1 day ago», «an hour ago» …
# Это надёжный признак сегодняшнего турнира: всё мельче суток (секунды/минуты/часы) = сегодня.
_CREATED_AGO_RE = re.compile(r"(\d+|an?)\s+(second|minute|hour|day|week|month|year)s?\s+ago", re.IGNORECASE)

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

    def _get_text(self, url: str) -> str:
        """Fetch an idempotent AetherHub page with bounded transport retries."""
        for attempt in range(_GET_ATTEMPTS):
            try:
                return self._scraper.get(url, timeout=30).text
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                if attempt == _GET_ATTEMPTS - 1:
                    raise
                time.sleep(_GET_RETRY_BACKOFF_SECONDS * (2**attempt))
        raise AssertionError("unreachable")

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

    def _extract_created_ago(self, container, today: date) -> date | None:
        """Дата создания турнира из текста «N <unit> ago» внизу ячейки.

        Всё мельче суток (секунды/минуты/часы) → сегодня: турнир создают в день события.
        «just now» тоже сегодня. Недели/месяцы/годы — заведомо не сегодня.
        """
        if container is None:
            return None
        small = container.find("small", class_="text-muted")
        if small is None:
            return None
        text = small.get_text(strip=True).lower()
        if "just now" in text or "moment" in text:
            return today
        m = _CREATED_AGO_RE.search(text)
        if not m:
            return None
        qty = 1 if m.group(1) in ("a", "an") else int(m.group(1))
        unit = m.group(2)
        if unit in ("second", "minute", "hour"):
            return today
        if unit == "day":
            return today - timedelta(days=qty)
        if unit == "week":
            return today - timedelta(weeks=qty)
        return today - timedelta(days=(365 if unit == "year" else 30) * qty)

    def _parse_club_page(self, html: str, today: date | None = None) -> list[ClubTournamentLink]:
        soup = BeautifulSoup(html, "html.parser")
        today = today or date.today()
        results: list[ClubTournamentLink] = []
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            if not _TOURNEY_LINK_RE.search(href):
                continue
            url = href if href.startswith("http") else f"https://aetherhub.com{href}"
            if url in seen:
                continue
            seen.add(url)

            name = a.get_text(strip=True)
            if not name:
                continue

            container = a.find_parent("div", class_="w-100") or a.find_parent("tr") or a.find_parent("li") or a.parent
            cell_text = container.get_text(" ", strip=True) if container else name
            # Дата из имени авторитетна (это дата события); «N ago» — фолбэк, когда даты в имени нет.
            tournament_date = (
                self._extract_date(name) or self._extract_created_ago(container, today) or self._extract_date(cell_text)
            )

            results.append(
                ClubTournamentLink(
                    name=name,
                    url=url,
                    date=tournament_date,
                    is_pauper=bool(PAUPER_RE.search(cell_text)),
                )
            )

        return results

    def fetch_club_tournaments(self, club_url: str, today: date | None = None) -> list[ClubTournamentLink]:
        html = self._get_text(club_url)
        return self._parse_club_page(html, today=today)

    def find_todays_pauper_tournament(self, club_url: str, today: date | None = None) -> str | None:
        """URL сегодняшнего паупер-турнира клуба, либо None.

        Список клуба отсортирован свежими сверху, поэтому берём ПЕРВЫЙ турнир, который
        одновременно (1) паупер — по тексту ячейки: у Goldfish это подзаголовок
        «Constructed: Pauper Tourney», у Edinorog «Паупер …» в имени; и (2) сегодняшний —
        дата из имени либо «создан N часов назад» указывает на сегодня.
        ``today=None`` (debug) снимает проверку даты — возвращаем самый свежий паупер.
        """
        for link in self.fetch_club_tournaments(club_url, today=today):
            if link.is_pauper and (today is None or link.date == today):
                return link.url
        return None

    def find_tournament_url(self, club_url: str, event_date: date, tournament_format: str) -> str | None:
        """Find a club tournament by event date and format.

        The current migration is intentionally Pauper-only. Keeping the format in the
        interface prevents callers from silently attaching a Legacy/Modern URL.
        """
        by_date = self.tournament_urls_by_date(club_url, tournament_format)
        matches = by_date.get(event_date, [])
        if len(matches) > 1:
            raise ValueError(f"Multiple AetherHub Pauper tournaments found on {event_date.isoformat()}: {matches}")
        return matches[0] if matches else None

    def tournament_urls_by_date(self, club_url: str, tournament_format: str) -> dict[date, list[str]]:
        """Load the organizer's public tournament history once and index it by date."""
        if not PAUPER_RE.fullmatch(tournament_format.strip()):
            raise ValueError(f"Unsupported AetherHub tournament format: {tournament_format}")
        owner_match = re.search(r"/User/([^/?#]+)", club_url, re.IGNORECASE)
        if not owner_match:
            raise ValueError(f"Cannot extract AetherHub owner from URL: {club_url}")
        owner = owner_match.group(1)
        start = 0
        page_size = 100
        by_date: dict[date, list[str]] = {}
        while True:
            payload = {
                "draw": 1,
                "start": start,
                "length": page_size,
                "search": {"value": owner, "regex": False},
                "order": [{"column": 2, "dir": "desc"}],
                "columns": [
                    {
                        "data": field,
                        "name": field,
                        "searchable": True,
                        "orderable": field in ("date", "finished"),
                        "search": {"value": "", "regex": False},
                    }
                    for field in ("name", "owner", "date", "finished")
                ],
            }
            response = self._scraper.post("https://aetherhub.com/Tourney/FetchPublicTourneys", json=payload, timeout=30)
            response.raise_for_status()
            body = response.json()
            rows = body.get("model", [])
            for row in rows:
                try:
                    row_date = datetime.fromisoformat(row["date"]).date()
                except (KeyError, TypeError, ValueError):
                    continue
                same_owner = str(row.get("owner", "")).casefold() == owner.casefold()
                # Goldfish is a dedicated Pauper organizer and uses date-only names.
                requested_format = owner.casefold() == "goldfish" or PAUPER_RE.search(str(row.get("name", "")))
                if same_owner and requested_format:
                    url = f"https://aetherhub.com/Tourney/RoundTourney/{int(row['id'])}"
                    by_date.setdefault(row_date, []).append(url)
            start += len(rows)
            if not rows or start >= int(body.get("recordsFiltered", start)):
                break
        return {event_date: list(dict.fromkeys(urls)) for event_date, urls in by_date.items()}

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

        main_html = self._get_text(url)
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
            # edinorog-формат: главная ?p=N отдаёт matchList СО счётом («Match Results»).
            pairings = self._parse_pairings_page(self._get_text(f"{url}?p={rn}"))
            if not pairings:
                # js-формат: на главной паринги подгружаются JS-ом, в серверном HTML
                # только standings. Берём пары с публичного pairings-эндпоинта.
                # ВАЖНО: у js-формата СЧЁТА НЕТ — у RoundTourneyPublicPairings колонка
                # «Match Results» пустая во всех раундах (проверено), поэтому
                # player_wins/opponent_wins останутся None. Только пары и столы.
                pairings = self._parse_pairings_page(self._get_text(self._pairings_url(tourney_id, rn)))
            signature = frozenset((p.player, p.opponent) for p in pairings)
            if rn > 1 and signature and signature == prev_signature:
                break  # clamped duplicate of the previous round → phantom, stop here
            rounds.append(AetherhubRound(number=rn, pairings=pairings))
            prev_signature = signature

        players = self._players_from_pairings(rounds[0].pairings) if rounds else []
        standings, _ = self._parse_standings_page(main_html)

        return AetherhubTournamentData(url=url, players=players, rounds=rounds, standings=standings)
