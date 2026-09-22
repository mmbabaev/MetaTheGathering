"""Parser and cache for the https://mtgdecks.net/Pauper/winrates table.

The page is server-rendered: each `<tr class="item">` carries the deck name,
the overall winrate (as a fraction) and the number of matches; the header row
lists the opponent archetypes and each `td.winrate-cell` after the "Overall"
column carries the head-to-head winrate (integer percents) of the row's deck
against that opponent.

The winrates path is behind a Cloudflare challenge for fresh sessions, but it
loads fine right after warming the session on the format meta page (which sets
a session cookie). As a last resort the cache falls back to the last good
parse persisted on disk, or to the bundled snapshot shipped with the repo.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cloudscraper
import requests
from bs4 import BeautifulSoup

WINRATES_URL = "https://mtgdecks.net/Pauper/winrates"
WARMUP_URL = "https://mtgdecks.net/Pauper"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_DATA_DIR = Path(__file__).parent / "data"
_PERSIST_PATH = _DATA_DIR / "winrates_cache.json"
_BUNDLED_PATH = _DATA_DIR / "winrates_snapshot.json"

_NOT_SET = object()

_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass(frozen=True)
class Deck:
    name: str
    overall_winrate: float
    matches: int


@dataclass(frozen=True)
class WinrateData:
    decks: list[Deck]
    matrix: dict[str, dict[str, int]]
    fetched_at: float
    source_url: str = WINRATES_URL

    def winrate_against(self, deck: str, opponent: str) -> int | None:
        return self.matrix.get(deck, {}).get(opponent)


def _looks_valid(text: str) -> bool:
    return len(text) > 10_000 and '<table id="winrates"' in text and "data-name" in text


def fetch_winrates_html() -> str:
    """Download the winrates page via a warmed session (Cloudflare-friendly)."""
    session = requests.Session()
    session.headers.update(_HEADERS)
    try:
        session.get(WARMUP_URL, timeout=30)
        resp = session.get(WINRATES_URL, timeout=30)
        if resp.ok and _looks_valid(resp.text):
            return resp.text
        warmup_reason = f"HTTP {resp.status_code}"
    except requests.RequestException as exc:
        warmup_reason = str(exc)

    try:
        resp = cloudscraper.create_scraper().get(WINRATES_URL, headers=_HEADERS, timeout=40)
        if resp.ok and _looks_valid(resp.text):
            return resp.text
    except requests.RequestException:
        pass

    resp = requests.get(WINRATES_URL, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    if not _looks_valid(resp.text):
        raise ValueError(f"winrates table not found in the page (warmup failed: {warmup_reason})")
    return resp.text


def parse_winrates(html: str, *, fetched_at: float | None = None) -> WinrateData:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="winrates")
    if table is None:
        raise ValueError("winrates table not found")

    column_names: list[str] = []
    thead = table.find("thead")
    for th in thead.find_all("th") if thead else []:
        text = th.get_text(" ", strip=True).strip()
        if text and text != "Overall":
            column_names.append(text)

    decks: list[Deck] = []
    matrix: dict[str, dict[str, int]] = {}
    tbody = table.find("tbody")
    rows = tbody.select("tr.item") if tbody else []
    for tr in rows:
        name = tr.get("data-name")
        if not name:
            continue
        try:
            overall = float(tr.get("data-winrate")) * 100.0
        except (TypeError, ValueError):
            overall = 50.0
        try:
            matches = int(tr.get("data-matches"))
        except (TypeError, ValueError):
            matches = 0
        cells = tr.find_all("td", recursive=False)
        vs: dict[str, int] = {}
        for column, cell in zip(column_names, cells[2:], strict=False):
            winrate = cell.get("data-winrate")
            if winrate is not None:
                try:
                    vs[column] = int(winrate)
                except ValueError:
                    pass
        decks.append(Deck(name=name, overall_winrate=round(overall, 1), matches=matches))
        matrix[name] = vs

    decks.sort(key=lambda deck: (deck.matches, deck.name), reverse=True)
    return WinrateData(decks=decks, matrix=matrix, fetched_at=fetched_at or time.time())


def to_dict(data: WinrateData) -> dict:
    return {
        "source_url": data.source_url,
        "fetched_at": data.fetched_at,
        "decks": [
            {"name": deck.name, "overall_winrate": deck.overall_winrate, "matches": deck.matches} for deck in data.decks
        ],
        "matrix": data.matrix,
    }


def from_dict(payload: dict) -> WinrateData:
    decks = [
        Deck(
            name=item["name"],
            overall_winrate=float(item["overall_winrate"]),
            matches=int(item["matches"]),
        )
        for item in payload["decks"]
    ]
    return WinrateData(
        decks=decks,
        matrix={deck: dict(vs) for deck, vs in payload["matrix"].items()},
        fetched_at=float(payload["fetched_at"]),
        source_url=payload.get("source_url", WINRATES_URL),
    )


def _load_from_json(path: Path | None) -> WinrateData | None:
    if path is None:
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return from_dict(json.load(handle))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


class WinrateCache:
    """Thread-safe cache that prefers fresh live data and falls back to disk.

    On a successful fetch the result is persisted to `winrates_cache.json`
    (gitignored). If the live fetch fails, the last known good data — the
    in-memory copy, the persisted file, or the bundled snapshot — is served.
    """

    def __init__(
        self,
        ttl_seconds: int = 6 * 3600,
        persist_path: Path | None = None,
        bundled_path: Path | None | object = _NOT_SET,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self._persist_path = persist_path if persist_path is not None else _PERSIST_PATH
        self._bundled_path = _BUNDLED_PATH if bundled_path is _NOT_SET else bundled_path
        self._data: WinrateData | None = _load_from_json(self._persist_path)
        if self._data is None and self._bundled_path is not None:
            self._data = _load_from_json(self._bundled_path)
        self._lock = threading.Lock()

    def get(self, *, force: bool = False) -> WinrateData:
        with self._lock:
            candidate = self._data
            needs_fetch = force or candidate is None or time.time() - candidate.fetched_at > self.ttl_seconds
            if needs_fetch:
                last_known = candidate
                if last_known is None:
                    last_known = _load_from_json(self._persist_path) or _load_from_json(self._bundled_path)
                try:
                    candidate = parse_winrates(fetch_winrates_html())
                    self._persist(candidate)
                except Exception:
                    if last_known is None:
                        raise
                    candidate = last_known
            self._data = candidate
            return candidate

    def _persist(self, data: WinrateData) -> None:
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._persist_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(to_dict(data)), encoding="utf-8")
            tmp.replace(self._persist_path)
        except OSError:
            pass
