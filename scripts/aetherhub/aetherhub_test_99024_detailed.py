"""Test: detailed analysis of second-format aetherhub tournament (99024)."""

import sys

sys.path.insert(0, "/Users/mbabaev/Develop/MetaGatherer")

import cloudscraper
from bs4 import BeautifulSoup

URL = "https://aetherhub.com/Tourney/RoundTourney/99024"

scraper = cloudscraper.create_scraper()
print(f"Fetching {URL} ...")

resp = scraper.get(URL, timeout=30)
print(f"Status: {resp.status_code}\n")

if resp.status_code != 200:
    print("FAILED — non-200 response")
    sys.exit(1)

if "Just a moment" in resp.text or "cf-browser-verification" in resp.text:
    print("FAILED — Cloudflare challenge page returned")
    sys.exit(1)

# Save raw HTML for analysis
with open("/Users/mbabaev/Develop/MetaGatherer/scripts/aetherhub_99024.html", "w", encoding="utf-8") as f:
    f.write(resp.text)
print("Saved raw HTML to scripts/aetherhub_99024.html\n")

soup = BeautifulSoup(resp.text, "html.parser")

# Look for all content with "Round" in it
print("=" * 60)
print("SEARCHING FOR ROUND INFORMATION")
print("=" * 60)

# Find all elements that contain "Round" text
all_elements = soup.find_all(string=lambda text: text and "Round" in text)
print(f"Found {len(all_elements)} elements containing 'Round'")
for i, elem in enumerate(all_elements[:15]):
    parent_tag = elem.parent.name if elem.parent else "no parent"
    parent_class = elem.parent.get("class", []) if elem.parent else []
    print(f"  {i + 1}. [{parent_tag}.{parent_class}] {elem.strip()[:80]}")

# Look at the results tab more carefully
print("\n" + "=" * 60)
print("RESULTS TAB DETAILED ANALYSIS")
print("=" * 60)
results_tab = soup.find("div", {"id": "tab_results"})
if results_tab:
    # Print the first 2000 chars of results tab HTML
    print("Results tab HTML (first 2000 chars):")
    print(str(results_tab)[:2000])
    print("\n...")

    # Find all divs in results
    all_divs = results_tab.find_all("div", recursive=True)
    print(f"\nTotal divs in results tab: {len(all_divs)}")

    # Look for buttons or headers that might indicate rounds
    buttons = results_tab.find_all("button")
    print(f"\nButtons in results tab: {len(buttons)}")
    for i, btn in enumerate(buttons[:10]):
        print(f"  {i + 1}. {btn.text.strip()[:50]} - classes: {btn.get('class')}")

    # Look for accordions or collapsible content
    accordions = results_tab.find_all(attrs={"class": lambda c: c and "accordion" in str(c).lower() if c else False})
    print(f"\nAccordion elements: {len(accordions)}")

    # Look for cards
    cards = results_tab.find_all(attrs={"class": lambda c: c and "card" in str(c).lower() if c else False})
    print(f"\nCard elements: {len(cards)}")
    for i, card in enumerate(cards[:3]):
        print(f"  {i + 1}. Classes: {card.get('class')} - Text preview: {card.get_text()[:100]}")

# Look at pairings tab
print("\n" + "=" * 60)
print("PAIRINGS TAB DETAILED ANALYSIS")
print("=" * 60)
pairings_tab = soup.find("div", {"id": "tab_pairings"})
if pairings_tab:
    print("Pairings tab HTML:")
    print(str(pairings_tab))

print("\nDone - check scripts/aetherhub_99024.html for full page source")
