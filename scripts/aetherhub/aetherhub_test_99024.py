"""Test: fetch and parse second-format aetherhub tournament (99024)."""

import sys

sys.path.insert(0, "/Users/mbabaev/Develop/MetaGatherer")

import cloudscraper
from bs4 import BeautifulSoup

from services.aetherhub_models import AetherhubTournamentData

URL = "https://aetherhub.com/Tourney/RoundTourney/99024"

scraper = cloudscraper.create_scraper()
print(f"Fetching {URL} ...")

resp = scraper.get(URL, timeout=30)
print(f"Status: {resp.status_code}")

if resp.status_code != 200:
    print("FAILED — non-200 response")
    sys.exit(1)

if "Just a moment" in resp.text or "cf-browser-verification" in resp.text:
    print("FAILED — Cloudflare challenge page returned")
    sys.exit(1)

soup = BeautifulSoup(resp.text, "html.parser")
title = soup.find("title")
print(f"Page title: {title.text if title else '(none)'}\n")

# 1. Extract players from standings table
print("=" * 60)
print("EXTRACTING PLAYERS FROM STANDINGS")
print("=" * 60)
standings_table = soup.find("table")
if standings_table:
    rows = standings_table.find_all("tr")[1:]  # Skip header
    players = []
    for row in rows:
        cells = row.find_all("td")
        if len(cells) >= 2:
            name_cell = cells[1]
            # Try to get player name from link or text
            link = name_cell.find("a")
            if link:
                player_name = link.text.strip()
            else:
                player_name = name_cell.text.strip()
            if player_name:
                players.append(player_name)
    print(f"Found {len(players)} players:")
    for i, p in enumerate(players[:10], 1):
        print(f"  {i}. {p}")
    if len(players) > 10:
        print(f"  ... and {len(players) - 10} more")
else:
    print("No standings table found!")
    players = []

# 2. Extract pairings from the pairings tab
print("\n" + "=" * 60)
print("EXTRACTING PAIRINGS")
print("=" * 60)
pairings_tab = soup.find("div", {"id": "tab_pairings"})
if pairings_tab:
    print(f"Pairings tab found, content length: {len(str(pairings_tab))}")

    # Look for round indicators
    round_divs = pairings_tab.find_all("div", recursive=True)
    print(f"Total divs in pairings tab: {len(round_divs)}")

    # Look for text containing "Round"
    all_text = pairings_tab.get_text()
    if "Round" in all_text:
        lines = all_text.split("\n")
        round_lines = [line.strip() for line in lines if "Round" in line and line.strip()]
        print(f"\nLines containing 'Round': {len(round_lines)}")
        for line in round_lines[:10]:
            print(f"  {line}")

    # Look for pairing structure
    print("\nLooking for pairing patterns...")
    # Check for common pairing indicators
    vs_elements = pairings_tab.find_all(string=lambda text: text and "vs" in text.lower())
    print(f"Elements with 'vs': {len(vs_elements)}")
    if vs_elements:
        for i, elem in enumerate(vs_elements[:5]):
            print(f"  {i + 1}. {elem.strip()[:100]}")

    # Look for rows or divs that might be pairings
    pairing_rows = pairings_tab.find_all(
        "div", class_=lambda c: c and any(x in str(c).lower() for x in ["row", "pairing", "match"])
    )
    print(f"\nDivs with pairing-like classes: {len(pairing_rows)}")
    for i, div in enumerate(pairing_rows[:3]):
        print(f"  {i + 1}. Classes: {div.get('class')} - Text: {div.get_text()[:100]}")

    # Try to find all links (player names)
    links = pairings_tab.find_all("a")
    print(f"\nLinks in pairings tab: {len(links)}")
    link_texts = [line.text.strip() for line in links if line.text.strip()]
    if link_texts:
        print(f"  First 10 links: {link_texts[:10]}")
else:
    print("No pairings tab found!")

# 3. Check results tab
print("\n" + "=" * 60)
print("EXTRACTING RESULTS")
print("=" * 60)
results_tab = soup.find("div", {"id": "tab_results"})
if results_tab:
    print(f"Results tab found, content length: {len(str(results_tab))}")
    all_text = results_tab.get_text()
    if "Round" in all_text:
        lines = all_text.split("\n")
        round_lines = [line.strip() for line in lines if "Round" in line and line.strip()]
        print(f"Lines containing 'Round': {len(round_lines)}")
        for line in round_lines[:10]:
            print(f"  {line}")
else:
    print("No results tab found!")

# 4. Try to construct AetherhubTournamentData
print("\n" + "=" * 60)
print("ATTEMPTING TO BUILD AetherhubTournamentData")
print("=" * 60)

try:
    # For now, create a mock structure
    rounds = []

    # We'll need to figure out the actual parsing logic based on the output
    print("Need to analyze the HTML structure to extract rounds and pairings properly")
    print(f"Players extracted: {len(players)}")

    tournament_data = AetherhubTournamentData(url=URL, players=players, rounds=rounds)
    print("\nCreated AetherhubTournamentData:")
    print(f"  URL: {tournament_data.url}")
    print(f"  Players: {len(tournament_data.players)}")
    print(f"  Rounds: {len(tournament_data.rounds)}")

except Exception as e:
    print(f"Error creating tournament data: {e}")

print("\nSUCCESS — analysis complete")
