"""Reverse-engineer the API endpoint for adding a player to an AetherHub tournament.

Usage: python scripts/aetherhub/aetherhub_find_add_player_api.py
"""

import re
import sys

sys.path.insert(0, "/Users/mbabaev/Develop/MetaGatherer")

import cloudscraper

TOURNAMENT_ID = "99131"
EDIT_URL = f"https://aetherhub.com/Tourney/EditTourney/{TOURNAMENT_ID}"
BASE_URL = "https://aetherhub.com"

scraper = cloudscraper.create_scraper()

print("=" * 60)
print(f"FETCHING EDIT PAGE: {EDIT_URL}")
print("=" * 60)

resp = scraper.get(EDIT_URL, timeout=30)
print(f"Status: {resp.status_code}")
print(f"Content-Type: {resp.headers.get('content-type', 'unknown')}")

html = resp.text

# Save raw HTML for manual inspection
with open("/Users/mbabaev/Develop/MetaGatherer/scripts/aetherhub/edit_tourney_99131.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"Saved HTML ({len(html)} bytes) → scripts/aetherhub/edit_tourney_99131.html")

# Extract all JS file URLs
print("\n" + "=" * 60)
print("JS FILES REFERENCED ON PAGE")
print("=" * 60)
js_urls = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html)
for url in js_urls:
    full = url if url.startswith("http") else f"https://aetherhubassets.b-cdn.net{url}" if url.startswith("/") else url
    print(f"  {url}")

# Look for AJAX/fetch patterns directly in the HTML (inline scripts)
print("\n" + "=" * 60)
print("API PATTERNS IN INLINE SCRIPTS")
print("=" * 60)

patterns = [
    r'(?:url|action)\s*[=:]\s*["\']([^"\']*(?:player|participant|add|register|tourney)[^"\']*)["\']',
    r'(?:fetch|post|get|ajax)\s*\(\s*["\']([^"\']+)["\']',
    r'/Tourney/[A-Za-z]+[^"\'<> ]*',
    r'/api/[^"\'<> ]+',
    r"AddPlayer|AddParticipant|RegisterPlayer|EnrollPlayer",
]

for pat in patterns:
    matches = re.findall(pat, html, re.IGNORECASE)
    unique = list(dict.fromkeys(matches))
    if unique:
        print(f"\nPattern: {pat}")
        for m in unique[:10]:
            print(f"  {m}")

# Look for form actions
print("\n" + "=" * 60)
print("FORM ACTIONS")
print("=" * 60)
forms = re.findall(r"<form[^>]+>", html, re.IGNORECASE)
for form in forms:
    print(f"  {form[:200]}")

# Look for CSRF / request verification tokens
print("\n" + "=" * 60)
print("CSRF / ANTIFORGERY TOKENS")
print("=" * 60)
tokens = re.findall(r'(?:__RequestVerificationToken|_token|csrf)[^>]*value=["\']([^"\']+)["\']', html, re.IGNORECASE)
for t in tokens:
    print(f"  {t[:80]}")

# Also grab token from meta tags
meta_tokens = re.findall(
    r'<meta[^>]+name=["\']([^"\']*token[^"\']*)["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE
)
for name, content in meta_tokens:
    print(f"  meta {name}: {content[:80]}")

# Look for tournament-specific JS files and fetch them
print("\n" + "=" * 60)
print("FETCHING EDIT-RELATED JS FILES")
print("=" * 60)

edit_js_patterns = [r"edit", r"tourney", r"player", r"participant"]
for url in js_urls:
    if any(p in url.lower() for p in edit_js_patterns):
        full = url if url.startswith("http") else f"https://aetherhubassets.b-cdn.net{url}"
        print(f"\nFetching: {full}")
        try:
            js_resp = scraper.get(full, timeout=15)
            print(f"  Status: {js_resp.status_code}, Size: {len(js_resp.text)} bytes")
            if js_resp.status_code == 200:
                js_text = js_resp.text
                fname = url.split("/")[-1].split("?")[0]
                with open(f"/Users/mbabaev/Develop/MetaGatherer/scripts/aetherhub/{fname}", "w", encoding="utf-8") as f:
                    f.write(js_text)
                print(f"  Saved → scripts/aetherhub/{fname}")

                # Search for player-add endpoints inside JS
                for pat in patterns:
                    matches = re.findall(pat, js_text, re.IGNORECASE)
                    unique = list(dict.fromkeys(matches))
                    if unique:
                        print(f"  Pattern {pat}: {unique[:5]}")
        except Exception as e:
            print(f"  Error: {e}")

print("\nDone.")
