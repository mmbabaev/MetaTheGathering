"""Analyze HAR file to find pairings API endpoint."""

import json
import sys

har_path = sys.argv[1] if len(sys.argv) > 1 else "/Users/mbabaev/Downloads/aetherhub.com.har"

print(f"Analyzing HAR file: {har_path}")

with open(har_path, "r") as f:
    har_data = json.load(f)

entries = har_data["log"]["entries"]
print(f"Total requests: {len(entries)}")

# Look for requests containing pairings or match data
print("\n" + "=" * 60)
print("Requests that might contain pairings:")
print("=" * 60)

for entry in entries:
    url = entry["request"]["url"]
    method = entry["request"]["method"]

    # Check if URL looks relevant
    if any(keyword in url.lower() for keyword in ["pair", "match", "round", "tourney", "99024"]):
        status = entry["response"]["status"]
        content_type = next(
            (h["value"] for h in entry["response"]["headers"] if h["name"].lower() == "content-type"), "unknown"
        )

        print(f"\n{method} {url}")
        print(f"  Status: {status}")
        print(f"  Content-Type: {content_type}")

        # Check response content
        if "content" in entry["response"] and "text" in entry["response"]["content"]:
            text = entry["response"]["content"]["text"]
            if "Руденко" in text or "Гусаров" in text:
                print("  ✓✓✓ CONTAINS PAIRINGS DATA!")
                print(f"  Response size: {len(text)} bytes")
                print(f"  First 500 chars: {text[:500]}")
