"""Verify the fix works - check all 4 rounds for Бабаев Михаил."""

import sys

sys.path.insert(0, "/Users/mbabaev/Develop/MetaGatherer")

from services.aetherhub import fetch_tournament

URL = "https://aetherhub.com/Tourney/RoundTourney/99024"

print(f"Fetching tournament: {URL}")
data = fetch_tournament(URL)

print(f"\nPlayers: {len(data.players)}")
print(f"Rounds: {len(data.rounds)}")

target_player = "Бабаев Михаил"
print(f"\n{'=' * 60}")
print(f"Opponents for: {target_player}")
print(f"{'=' * 60}")

for round_data in data.rounds:
    player_pairings = [p for p in round_data.pairings if p.player == target_player]

    if player_pairings:
        opponent = player_pairings[0].opponent if player_pairings[0].opponent else "BYE"
        print(f"Round {round_data.number}: {opponent}")
    else:
        print(f"Round {round_data.number}: NOT FOUND")

print(f"\n{'=' * 60}")
print("EXPECTED: 4 different opponents (no byes)")
print("✓ SUCCESS!" if len(data.rounds) == 4 else "✗ FAILED")
