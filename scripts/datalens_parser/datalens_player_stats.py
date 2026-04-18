import sys
import requests
from datalens_parser import PlayerChoicesResponse

URL = "https://datalens.yandex/charts/api/run"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain",
    "Origin": "https://datalens.yandex",
    "Referer": "https://datalens.yandex/6dr39r9a9l9mt?state=228a5e4d170",
    "x-dl-component": "ui",
    "x-dash-info": "dashId6dr39r9a9l9mtdashTabIdZa",
    "x-dl-display-mode": "basic",
}


def fetch_player_stats(player_name: str) -> list:
    payload = {
        "id": "jsaobu3lpeos6",
        "params": {
            "klub_77wt": "",
            "data_v9da": "__interval_2023-01-01T00:00:00.000Z___relative_-0d",
            "igrok_4vy1": player_name,
            "uchastnik_0zyi": player_name,
        },
        "widgetConfig": {"actionParams": {"enable": True}},
        "responseOptions": {"includeConfig": True, "includeLogs": False},
    }

    r = requests.post(URL, json=payload, headers=HEADERS, timeout=60)
    r.raise_for_status()

    return PlayerChoicesResponse(r.json()).decks()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python datalens_player_stats.py 'Фамилия Имя'")
        sys.exit(1)

    player_name = sys.argv[1]
    decks = fetch_player_stats(player_name)

    if not decks:
        print(f"Нет данных для игрока: {player_name}")
        sys.exit(0)

    print(f"\n{player_name} — {len(decks)} колод(ы)\n")
    print(f"{'Колода':<30} {'Матчей':>8} {'Винрейт':>10}")
    print("-" * 52)
    for deck in decks:
        print(f"{deck.name:<30} {deck.matches:>8} {deck.winrate:>9.1f}%")
