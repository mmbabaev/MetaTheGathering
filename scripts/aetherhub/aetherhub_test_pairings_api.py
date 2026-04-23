"""Test: Use the discovered pairings API endpoint."""

import sys

sys.path.insert(0, "/Users/mbabaev/Develop/MetaGatherer")

import json

import cloudscraper

URL = "https://aetherhub.com/Tourney/RoundTourney/99024"
TOURNAMENT_ID = "99024"

scraper = cloudscraper.create_scraper()

print("=" * 60)
print("TESTING PAIRINGS API ENDPOINT")
print("=" * 60)

# Try the endpoint we found in the JavaScript
endpoint = f"/Tourney/RoundTourneyPublicPairings?id={TOURNAMENT_ID}"
full_url = f"https://aetherhub.com{endpoint}"

print(f"\nEndpoint: {endpoint}")
print(f"Full URL: {full_url}")

try:
    resp = scraper.get(full_url, timeout=30)
    print(f"\nStatus: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('content-type', 'unknown')}")
    print(f"Size: {len(resp.text)} bytes")

    if resp.status_code == 200:
        # Save the response
        with open("/Users/mbabaev/Develop/MetaGatherer/scripts/pairings_api_response.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        print("✅ Saved response to scripts/pairings_api_response.html")

        # Try to parse as JSON
        try:
            data = json.loads(resp.text)
            print("\n✅ Valid JSON!")
            print(f"Type: {type(data)}")
            if isinstance(data, dict):
                print(f"Keys: {list(data.keys())}")
            elif isinstance(data, list):
                print(f"Array length: {len(data)}")
                if data:
                    print(f"First item: {data[0]}")
        except json.JSONDecodeError:
            # Not JSON, probably HTML
            print("\n📄 Response is HTML/text, not JSON")
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text, "html.parser")

            # Look for pairings structure
            print("\nAnalyzing HTML structure:")

            # Count divs, tables, etc.
            divs = soup.find_all("div")
            tables = soup.find_all("table")
            links = soup.find_all("a")

            print(f"  Divs: {len(divs)}")
            print(f"  Tables: {len(tables)}")
            print(f"  Links: {len(links)}")

            # Look for round information
            text_content = soup.get_text()
            if "Round" in text_content:
                lines = [line.strip() for line in text_content.split("\n") if "Round" in line and line.strip()]
                print(f"\n  Lines with 'Round': {len(lines)}")
                for line in lines[:10]:
                    print(f"    - {line}")

            # Look for player names or vs patterns
            if "vs" in text_content.lower():
                print("\n  ✅ Found 'vs' in content - likely contains pairings!")
                lines = [line.strip() for line in text_content.split("\n") if "vs" in line.lower() and line.strip()]
                print(f"  Lines with 'vs': {len(lines)}")
                for line in lines[:10]:
                    print(f"    - {line[:100]}")

            # Print first 1000 chars
            print("\nFirst 1000 characters of response:")
            print(resp.text[:1000])

except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback

    traceback.print_exc()

# Try with round parameter
print("\n" + "=" * 60)
print("TRYING WITH ROUND PARAMETER")
print("=" * 60)

for round_num in [1, 2, 3, 4]:
    endpoint = f"/Tourney/RoundTourneyPublicPairings?id={TOURNAMENT_ID}&round={round_num}"
    full_url = f"https://aetherhub.com{endpoint}"
    print(f"\nRound {round_num}: {endpoint}")

    try:
        resp = scraper.get(full_url, timeout=30)
        print(f"  Status: {resp.status_code}, Size: {len(resp.text)} bytes")

        if resp.status_code == 200 and len(resp.text) > 100:
            # Save if substantial content
            with open(
                f"/Users/mbabaev/Develop/MetaGatherer/scripts/pairings_round_{round_num}.html", "w", encoding="utf-8"
            ) as f:
                f.write(resp.text)
            print(f"  ✅ Saved to scripts/pairings_round_{round_num}.html")

            # Quick check for content
            if "vs" in resp.text.lower():
                print("  ✅ Contains 'vs' - likely has pairings!")
            elif "Round" in resp.text:
                print("  ✅ Contains 'Round' text")

    except Exception as e:
        print(f"  ❌ Error: {str(e)[:50]}")
