"""Regression: AetherHub must not produce phantom rounds.

Observed on Edinorog tournament 99847 (Паупер 01.06.2026): the bot showed 6 rounds
while AetherHub had only 4. Root cause: AetherHub's pairings endpoint clamps an
out-of-range round number to the LAST real round (requesting ?p=5, ?p=6 returns
round 4's pairings verbatim). If `_parse_num_rounds` over-counts — which it can,
because during a live event the round navigation briefly exposes extra ?p=N tabs
(standings/results) that the link-scan fallback picks up — the import loop fetches
those phantom rounds and stores duplicates of the last real round.

This test reproduces the clamp behaviour deterministically: 4 distinct rounds, with
?p=5 and ?p=6 returning round-4 data, and the main page advertising 6 rounds via
navigation links. `fetch_tournament` must yield exactly 4 rounds.
"""

from unittest.mock import MagicMock

from services.aetherhub_service import AetherhubService

URL = "https://aetherhub.com/Tourney/RoundTourney/99847"
TID = "99847"


def _pairings_table(pairs: list[tuple[str, str]]) -> str:
    rows = "".join(f"<tr><td>1</td><td>{p1}</td><td>{p2}</td></tr>" for p1, p2 in pairs)
    return f"<html><body><table id='matchList'><tr><th>#</th><th>P1</th><th>P2</th></tr>{rows}</table></body></html>"


# 4 real rounds, each with a distinct pairing set
_ROUND_PAIRS = {
    1: [("Alice", "Bob"), ("Carol", "Dave")],
    2: [("Alice", "Carol"), ("Bob", "Dave")],
    3: [("Alice", "Dave"), ("Bob", "Carol")],
    4: [("Alice", "Bob"), ("Carol", "Dave"), ("Eve", "Frank")],
}


def _pairings_url(p: int) -> str:
    return f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={TID}&p={p}"


def _build_html_map() -> dict[str, str]:
    # Main page: no numberOfRounds span, no tab_pairings data-page → fallback scans
    # ?p=N links. During the live event these briefly went up to 6 (standings tabs).
    nav = "".join(f'<a href="?p={p}">{p}</a>' for p in range(1, 7))
    main = f"<html><body><div>{nav}</div><div id='tab_results'><table></table></div></body></html>"

    html = {URL: main}
    # Main page ?p=N has no matchList here → fetch_tournament falls back to the
    # public pairings endpoint (this regression is about phantom-round clamping).
    for p in range(1, 7):
        html[f"{URL}?p={p}"] = "<html><body></body></html>"
    for p in range(1, 5):
        html[_pairings_url(p)] = _pairings_table(_ROUND_PAIRS[p])
    # AetherHub clamps out-of-range rounds to the last real round (round 4)
    for p in (5, 6):
        html[_pairings_url(p)] = _pairings_table(_ROUND_PAIRS[4])
    return html


def _mock_scraper(html_by_url: dict[str, str]) -> MagicMock:
    scraper = MagicMock()

    def get(url, **kwargs):
        resp = MagicMock()
        resp.text = html_by_url[url]
        return resp

    scraper.get.side_effect = get
    return scraper


def test_fetch_tournament_ignores_clamped_phantom_rounds():
    svc = AetherhubService(scraper=_mock_scraper(_build_html_map()))
    data = svc.fetch_tournament(URL)

    assert len(data.rounds) == 4, (
        f"Expected 4 rounds, got {len(data.rounds)} — phantom rounds from AetherHub's "
        f"out-of-range clamp leaked in (rounds 5/6 duplicate round 4)."
    )
