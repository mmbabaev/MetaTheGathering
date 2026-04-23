"""Parse pairings from the API endpoint and create AetherhubTournamentData."""

import sys

sys.path.insert(0, "/Users/mbabaev/Develop/MetaGatherer")

import cloudscraper
from bs4 import BeautifulSoup

from services.aetherhub_models import AetherhubPairing, AetherhubRound, AetherhubTournamentData

URL = "https://aetherhub.com/Tourney/RoundTourney/99024"
TOURNAMENT_ID = "99024"

scraper = cloudscraper.create_scraper()

print("=" * 60)
print("EXTRACTING TOURNAMENT DATA")
print("=" * 60)

# Step 1: Get players from standings
print("\n1. Fetching standings...")
resp = scraper.get(URL, timeout=30)
soup = BeautifulSoup(resp.text, "html.parser")

standings_table = soup.find("table")
players = []
if standings_table:
    rows = standings_table.find_all("tr")[1:]  # Skip header
    for row in rows:
        cells = row.find_all("td")
        if len(cells) >= 2:
            name_cell = cells[1]
            link = name_cell.find("a")
            if link:
                player_name = link.text.strip()
                if player_name:
                    players.append(player_name)

print(f"✅ Found {len(players)} players")

# Step 2: Get number of rounds from the page
num_rounds_elem = soup.find("span", {"id": "numberOfRounds"})
if num_rounds_elem:
    rounds_text = num_rounds_elem.text.strip()  # "Rounds 4"
    num_rounds = int(rounds_text.split()[-1])
    print(f"✅ Tournament has {num_rounds} rounds")
else:
    # Fallback: check data-page attribute
    pairings_tab = soup.find("div", {"id": "tab_pairings"})
    if pairings_tab and pairings_tab.get("data-page"):
        num_rounds = int(pairings_tab["data-page"])
        print(f"✅ Current round: {num_rounds} (from data-page)")
    else:
        num_rounds = 4  # Default
        print(f"⚠️  Using default: {num_rounds} rounds")

# Step 3: Get pairings for each round
print(f"\n2. Fetching pairings for rounds 1-{num_rounds}...")
rounds = []

for round_num in range(1, num_rounds + 1):
    print(f"\n  Round {round_num}:")
    endpoint = f"/Tourney/RoundTourneyPublicPairings?id={TOURNAMENT_ID}&round={round_num}"
    full_url = f"https://aetherhub.com{endpoint}"

    try:
        resp = scraper.get(full_url, timeout=30)
        if resp.status_code != 200:
            print(f"    ❌ Failed: {resp.status_code}")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"id": "matchList"})

        if not table:
            print("    ❌ No matchList table found")
            continue

        tbody = table.find("tbody")
        if not tbody:
            print("    ❌ No tbody found")
            continue

        pairings = []
        rows = tbody.find_all("tr")

        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 3:
                # Column 0: Table number
                # Column 1: Player 1
                # Column 2: Player 2

                player1_text = cells[1].get_text(strip=True)
                player2_text = cells[2].get_text(strip=True)

                # Extract just the name (remove points in parentheses)
                # Format: "Старостин Владислав (9 Points)"
                player1_name = player1_text.split("(")[0].strip()
                player2_name = player2_text.split("(")[0].strip() if player2_text else None

                # Handle byes (empty opponent)
                if not player2_name:
                    player2_name = None

                # Add pairing for player1
                if player1_name:
                    pairings.append(AetherhubPairing(player=player1_name, opponent=player2_name))

                    # If not a bye, add reverse pairing for player2
                    if player2_name:
                        pairings.append(AetherhubPairing(player=player2_name, opponent=player1_name))

        print(f"    ✅ Found {len(pairings)} pairings ({len(rows)} matches)")

        rounds.append(AetherhubRound(number=round_num, pairings=pairings))

    except Exception as e:
        print(f"    ❌ Error: {e}")

# Step 4: Create the final data structure
print("\n" + "=" * 60)
print("FINAL TOURNAMENT DATA")
print("=" * 60)

tournament_data = AetherhubTournamentData(url=URL, players=players, rounds=rounds)

print(f"\nURL: {tournament_data.url}")
print(f"Players: {len(tournament_data.players)}")
print(f"Rounds: {len(tournament_data.rounds)}")

# Print sample data
print("\nFirst 5 players:")
for i, player in enumerate(tournament_data.players[:5], 1):
    print(f"  {i}. {player}")

if tournament_data.rounds:
    print("\nRound 1 pairings (first 10):")
    round1 = tournament_data.rounds[0]
    for i, pairing in enumerate(round1.pairings[:10], 1):
        opponent = pairing.opponent if pairing.opponent else "BYE"
        print(f"  {i}. {pairing.player} vs {opponent}")

print("\n✅ SUCCESS - Tournament data extracted!")
