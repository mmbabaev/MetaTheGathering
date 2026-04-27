"""Add players to an AetherHub tournament via browser automation.

Connects to a real Chrome instance via CDP — bypasses bot detection.

STEP 1 — start Chrome with remote debugging (close Chrome first if open):
    /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \\
        --remote-debugging-port=9222 --no-first-run

STEP 2 — log in to AetherHub manually in that Chrome window

STEP 3 — run this script:
    python3 scripts/aetherhub_add_players.py https://aetherhub.com/Tourney/EditTourney/99131

Install deps:
    pip install playwright && playwright install chromium
"""

import asyncio
import sys

from playwright.async_api import async_playwright

CDP_URL = "http://localhost:9222"


def read_players() -> list[str]:
    print("Введи имена игроков (по одному на строку, пустая строка — конец):")
    players = []
    while True:
        try:
            line = input().strip()
        except EOFError:
            break
        if not line:
            break
        players.append(line)
    return players


async def run(tournament_url: str, players: list[str]) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        print(f"Подключён к Chrome. Открываю {tournament_url} ...")
        await page.goto(tournament_url)
        await page.wait_for_load_state("networkidle")

        if "/Account/Login" in page.url or "/login" in page.url.lower():
            print("Залогинься в браузере, затем нажми Enter здесь...")
            input()
            await page.wait_for_load_state("networkidle")

        print(f"Страница готова. Добавляю {len(players)} игроков...\n")

        ok = 0
        for i, name in enumerate(players, 1):
            print(f"[{i}/{len(players)}] {name} ... ", end="", flush=True)
            await page.fill("#tourneyplayer", name)
            async with page.expect_response(lambda r: "tourney" in r.url.lower(), timeout=10_000) as resp_info:
                await page.click("button[onclick*='addPlayerToTourney']")
            resp = await resp_info.value
            await page.wait_for_timeout(400)
            if resp.ok:
                ok += 1
                print("✓")
            else:
                print(f"✗ (HTTP {resp.status})")

        print(f"\nГотово: {ok}/{len(players)} добавлено.")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    tournament_url = sys.argv[1]
    players = read_players()
    if not players:
        print("Список пуст.")
        sys.exit(0)

    print()
    asyncio.run(run(tournament_url, players))


if __name__ == "__main__":
    main()
