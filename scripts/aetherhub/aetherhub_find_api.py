"""Test: Try to find API endpoint for pairings."""

import sys

sys.path.insert(0, "/Users/mbabaev/Develop/MetaGatherer")

import json
import re

import cloudscraper

URL = "https://aetherhub.com/Tourney/RoundTourney/99024"
TOURNAMENT_ID = "99024"

scraper = cloudscraper.create_scraper()

# Try different potential API endpoints
print("=" * 60)
print("TESTING POTENTIAL API ENDPOINTS")
print("=" * 60)

# Try to get the JavaScript file that loads pairings
js_url = "https://aetherhubassets.b-cdn.net/js/tourney-roundtourneypublic.js"
print(f"\n1. Fetching JavaScript file: {js_url}")
try:
    js_resp = scraper.get(js_url, timeout=10)
    if js_resp.status_code == 200:
        print(f"   Status: {js_resp.status_code}, Size: {len(js_resp.text)} bytes")

        # Save for analysis
        with open(
            "/Users/mbabaev/Develop/MetaGatherer/scripts/tourney-roundtourneypublic.js", "w", encoding="utf-8"
        ) as f:
            f.write(js_resp.text)
        print("   Saved to scripts/tourney-roundtourneypublic.js")

        # Look for API endpoints in the JavaScript
        api_patterns = [
            r'/api/[^"\']+',
            r'/Tourney/[^"\']+',
            r"GetPairings",
            r"GetRound",
            r"LoadPairings",
            r"fetch\([^)]+\)",
            r"\.get\([^)]+\)",
            r"xhr\.open\([^)]+\)",
        ]

        print("\n   Searching for API patterns in JavaScript:")
        for pattern in api_patterns:
            matches = re.findall(pattern, js_resp.text, re.IGNORECASE)
            if matches:
                unique_matches = list(set(matches))[:5]
                print(f"   Pattern '{pattern}': {unique_matches}")
    else:
        print(f"   Failed: {js_resp.status_code}")
except Exception as e:
    print(f"   Error: {e}")

# Try various potential API endpoints
potential_endpoints = [
    f"/Tourney/GetPairings/{TOURNAMENT_ID}",
    f"/Tourney/GetPairings/{TOURNAMENT_ID}/1",  # Round 1
    f"/Tourney/GetRound/{TOURNAMENT_ID}/1",
    f"/Tourney/RoundPairings/{TOURNAMENT_ID}/1",
    f"/api/tourney/{TOURNAMENT_ID}/pairings",
    f"/api/tourney/{TOURNAMENT_ID}/round/1",
    f"/Tourney/Pairings?id={TOURNAMENT_ID}&round=1",
]

print("\n" + "=" * 60)
print("TRYING POTENTIAL API ENDPOINTS")
print("=" * 60)

for endpoint in potential_endpoints:
    full_url = f"https://aetherhub.com{endpoint}"
    print(f"\n{endpoint}")
    try:
        resp = scraper.get(full_url, timeout=10)
        print(f"  Status: {resp.status_code}")
        if resp.status_code == 200:
            print(f"  Content-Type: {resp.headers.get('content-type', 'unknown')}")
            print(f"  Size: {len(resp.text)} bytes")
            if len(resp.text) < 500:
                print(f"  Content: {resp.text[:200]}")
            else:
                print(f"  Content (first 200 chars): {resp.text[:200]}")
                # Try to parse as JSON
                try:
                    data = resp.json()
                    print(f"  ✅ Valid JSON! Keys: {list(data.keys()) if isinstance(data, dict) else 'array'}")
                    # Save successful response
                    with open(
                        f"/Users/mbabaev/Develop/MetaGatherer/scripts/api_response_{endpoint.replace('/', '_')}.json",
                        "w",
                    ) as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    print(f"  Saved to scripts/api_response_{endpoint.replace('/', '_')}.json")
                except Exception:
                    pass
    except Exception as e:
        print(f"  Error: {str(e)[:100]}")

print("\n" + "=" * 60)
print("CHECKING DATA ATTRIBUTES")
print("=" * 60)
# The pairings tab had data-page="4" - maybe we can change that?
print("The pairings div has data-page='4' attribute")
print("This might indicate the round number in the URL or in an AJAX call")
