"""Compare HTML structure of edinorog vs JS format with ?p=1."""

import sys

sys.path.insert(0, "/Users/mbabaev/Develop/MetaGatherer")

import cloudscraper
from bs4 import BeautifulSoup

# Edinorog format
edinorog_url = "https://aetherhub.com/Tourney/RoundTourney/98984?p=1"
# JS format
js_url = "https://aetherhub.com/Tourney/RoundTourney/99024?p=1"

scraper = cloudscraper.create_scraper()

for name, url in [("Edinorog", edinorog_url), ("JS Format", js_url)]:
    print(f"\n{'=' * 60}")
    print(f"{name}: {url}")
    print(f"{'=' * 60}")

    resp = scraper.get(url, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")

    # Check all tables
    tables = soup.find_all("table")
    print(f"Total tables: {len(tables)}")

    for i, table in enumerate(tables):
        rows = table.find_all("tr")
        print(f"\nTable {i}: {len(rows)} rows")

        # Get headers
        headers = table.find_all("th")
        if headers:
            header_text = [h.get_text(strip=True) for h in headers]
            print(f"  Headers: {header_text}")

        # Get first data row
        if len(rows) > 1:
            first_row = rows[1]
            cells = first_row.find_all("td")
            if len(cells) >= 3:
                cell_text = [c.get_text(strip=True)[:30] for c in cells[:5]]
                print(f"  First row: {cell_text}")
