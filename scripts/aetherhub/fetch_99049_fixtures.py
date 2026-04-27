"""Fetch real Aetherhub HTML fixtures for tournament 99049 (GoldFish Pauper 24.04.2026).

Uses the same mechanism as the bot: cloudscraper.create_scraper().

It saves:
  - scripts/aetherhub/fixtures/99049_main.html
  - scripts/aetherhub/fixtures/99049_pairings_p1.html
  - scripts/aetherhub/fixtures/99049_pairings_p2.html
  - scripts/aetherhub/fixtures/99049_pairings_p3.html
  - scripts/aetherhub/fixtures/99049_pairings_p4.html
"""

from __future__ import annotations

from pathlib import Path

import cloudscraper

TOURNAMENT_ID = "99049"
BASE_URL = f"https://aetherhub.com/Tourney/RoundTourney/{TOURNAMENT_ID}"


def _assert_not_cloudflare(html: str) -> None:
    if "Just a moment" in html or "cf-browser-verification" in html:
        raise RuntimeError("Cloudflare challenge page returned; try again later or with a different IP.")


def main() -> None:
    out_dir = Path(__file__).resolve().parent / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)

    scraper = cloudscraper.create_scraper()

    targets: list[tuple[str, str]] = [
        ("99049_main.html", BASE_URL),
        ("99049_pairings_p1.html", f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={TOURNAMENT_ID}&p=1"),
        ("99049_pairings_p2.html", f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={TOURNAMENT_ID}&p=2"),
        ("99049_pairings_p3.html", f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={TOURNAMENT_ID}&p=3"),
        ("99049_pairings_p4.html", f"https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={TOURNAMENT_ID}&p=4"),
    ]

    for filename, url in targets:
        resp = scraper.get(url, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"Non-200 response for {url}: {resp.status_code}")
        _assert_not_cloudflare(resp.text)
        (out_dir / filename).write_text(resp.text, encoding="utf-8")
        print(f"saved {out_dir / filename} ({len(resp.text)} chars)")


if __name__ == "__main__":
    main()
