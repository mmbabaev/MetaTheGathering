"""Quick test: can cloudscraper fetch aetherhub tournament page?"""

import sys
import cloudscraper
from bs4 import BeautifulSoup

URL = "https://aetherhub.com/Tourney/RoundTourney/98984"

scraper = cloudscraper.create_scraper()
print(f"Fetching {URL} ...")

resp = scraper.get(URL, timeout=30)
print(f"Status: {resp.status_code}")
print(f"Content-Type: {resp.headers.get('content-type', 'unknown')}")
print(f"Body size: {len(resp.text)} chars")

if resp.status_code != 200:
    print("FAILED — non-200 response")
    sys.exit(1)

if "Just a moment" in resp.text or "cf-browser-verification" in resp.text:
    print("FAILED — Cloudflare challenge page returned")
    sys.exit(1)

soup = BeautifulSoup(resp.text, "html.parser")
title = soup.find("title")
print(f"Page title: {title.text if title else '(none)'}")

# Try to find player/pairing tables
tables = soup.find_all("table")
print(f"Tables found: {len(tables)}")
for i, t in enumerate(tables[:3]):
    headers = [th.text.strip() for th in t.find_all("th")]
    print(f"  Table {i}: headers = {headers}")

divs_with_player = soup.find_all(attrs={"class": lambda c: c and "player" in c.lower() if c else False})
print(f"Elements with 'player' in class: {len(divs_with_player)}")
if divs_with_player:
    print(f"  First: {divs_with_player[0]}")

print("\nSUCCESS — page fetched, parsing is possible")
