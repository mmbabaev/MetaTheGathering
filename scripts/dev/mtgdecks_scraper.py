"""
Scraper for mtgdecks.net Pauper meta data.
Uses cloudscraper (same as aetherhub.py) to bypass Cloudflare.

Usage:
    python3 scripts/dev/mtgdecks_scraper.py
    python3 scripts/dev/mtgdecks_scraper.py --winrates   # also scrape matchup matrix
    python3 scripts/dev/mtgdecks_scraper.py --json       # output JSON

Outputs:
    - Meta share table (deck, tier, meta%, winrate%, trend, decks, price)
    - Matchup winrate matrix (optional)
"""

import argparse
import json
import re
import sys

import cloudscraper
from bs4 import BeautifulSoup

BASE_URL = "https://mtgdecks.net"
META_URL = f"{BASE_URL}/Pauper"
WINRATES_URL = f"{BASE_URL}/Pauper/winrates"


def _scraper():
    return cloudscraper.create_scraper()


# ── Meta share table ─────────────────────────────────────────────────────────


def fetch_meta(scraper=None) -> list[dict]:
    """
    Fetch the main Pauper meta page and return list of archetypes:
        name, tier, meta_share, winrate, trend, decks, price
    """
    sc = scraper or _scraper()
    html = sc.get(META_URL, timeout=30).text
    return parse_meta_table(html)


def parse_meta_table(html: str) -> list[dict]:
    """
    Parse mtgdecks.net /Pauper page.

    Column layout (0-indexed):
        0: # (rank, empty in data rows)
        1: Name              class="sort"
        2: Meta Share        class="sort meta"  → <b class="meta-share hidden-xs">10.44%</b>
        3: Trend             class="sort meta small hidden-xs"
        4: Tier              → <span class="hidden-xs"> inside badge
        5: Winrate           class="sort number"
        6: Decks             class="sort number hidden-xs"
        7: Price             → <span class="paper option"> inside badge
        8: action (empty)
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    table = soup.find("table")
    if not table:
        return results

    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 7:
            continue

        # Skip header row
        if cells[1].name == "th" or cells[1].get_text(strip=True).lower() in ("name", "deck"):
            continue

        name = cells[1].get_text(strip=True)
        if not name:
            continue

        # Meta share: prefer the hidden-xs b tag (full precision like "10.44%")
        meta_b = cells[2].find("b", class_="hidden-xs")
        meta_share_raw = meta_b.get_text(strip=True) if meta_b else cells[2].get_text(strip=True)
        meta_share = float(meta_share_raw.rstrip("%")) if meta_share_raw.endswith("%") else None

        trend = cells[3].get_text(strip=True) if len(cells) > 3 else None

        # Tier: the non-mobile span
        tier_span = cells[4].find("span", class_="hidden-xs")
        tier = tier_span.get_text(strip=True) if tier_span else cells[4].get_text(strip=True)

        winrate_raw = cells[5].get_text(strip=True)
        winrate = float(winrate_raw.rstrip("%")) if winrate_raw.endswith("%") else None

        decks_raw = cells[6].get_text(strip=True) if len(cells) > 6 else ""
        decks = int(decks_raw.replace(",", "")) if decks_raw.isdigit() or decks_raw.replace(",", "").isdigit() else None

        # Price: paper price only (mtgo is hidden by default)
        paper_span = cells[7].find("span", class_=lambda c: c and "paper" in c) if len(cells) > 7 else None
        price_raw = paper_span.get_text(strip=True) if paper_span else ""
        price = int(re.sub(r"[^\d]", "", price_raw)) if re.search(r"\d", price_raw) else None

        results.append(
            {
                "name": name,
                "tier": tier,
                "meta_share": meta_share,
                "trend": trend,
                "winrate": winrate,
                "decks": decks,
                "price_paper": price,
            }
        )

    return results


# ── Winrate matrix ────────────────────────────────────────────────────────────


def fetch_winrates(scraper=None) -> dict[str, dict[str, dict]]:
    """
    Fetch /Pauper/winrates and return matchup matrix:
        {deck_name: {opponent_name: {"winrate": float, "matches": int}}}
    """
    sc = scraper or _scraper()
    html = sc.get(WINRATES_URL, timeout=30).text
    return parse_winrate_matrix(html)


def parse_winrate_matrix(html: str) -> dict[str, dict[str, dict]]:
    """
    Parse matchup matrix from mtgdecks.net /Pauper/winrates.

    Table structure:
        row[0]: header — col[0]="" col[1]="Overall" col[2+]="<DeckName>"
        row[1+]: data  — col[0]="<DeckName>" col[1]=overall, col[2+]=matchup cells

    Each matchup cell (class="winrate-cell"):
        <td class="winrate-cell" data-winrate="51">
          <div class="confidence-interval">50% - 53%</div>
          <b>51</b><span class="percent">%</span>
          <div class="matches-number">6,141 matches</div>
        </td>
    """
    soup = BeautifulSoup(html, "html.parser")
    matrix: dict[str, dict[str, dict]] = {}

    table = soup.find("table")
    if not table:
        print("WARNING: no table found on winrates page", file=sys.stderr)
        return matrix

    rows = table.find_all("tr")
    if not rows:
        return matrix

    # Header: skip col[0] (empty) and col[1] ("Overall") → col[2+] are opponent names
    header_cells = rows[0].find_all(["th", "td"])
    opponent_names = [c.get_text(strip=True) for c in header_cells[2:]]

    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        deck_name = cells[0].get_text(strip=True)
        if not deck_name:
            continue

        # col[1] = overall stats for this deck (skip)
        # col[2+] = matchup cells aligned with opponent_names
        matrix[deck_name] = {}
        for opp_name, cell in zip(opponent_names, cells[2:]):
            # data-winrate attribute is the fastest path
            wr_attr = cell.get("data-winrate")
            winrate = float(wr_attr) if wr_attr is not None else None

            matches_div = cell.find("div", class_="matches-number")
            matches = None
            if matches_div:
                m = re.search(r"([\d,]+)", matches_div.get_text())
                if m:
                    matches = int(m.group(1).replace(",", ""))

            if winrate is not None or matches is not None:
                matrix[deck_name][opp_name] = {
                    "winrate": winrate,
                    "matches": matches,
                }

    return matrix


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Scrape mtgdecks.net Pauper meta")
    parser.add_argument("--winrates", action="store_true", help="Also scrape matchup matrix")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = parser.parse_args()

    sc = _scraper()
    output = {}

    print("Fetching meta share table...", file=sys.stderr)
    meta = fetch_meta(sc)
    output["meta"] = meta

    if not meta:
        print("ERROR: no archetypes found — the page structure may have changed.", file=sys.stderr)
        print("Try inspecting the raw HTML:", file=sys.stderr)
        print(f"  curl -A 'Mozilla/5.0' {META_URL}", file=sys.stderr)

    if args.winrates:
        print("Fetching winrate matrix...", file=sys.stderr)
        matrix = fetch_winrates(sc)
        output["winrates"] = matrix

    if args.json:
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    # Pretty-print meta table
    print(f"\n{'DECK':<28} {'TIER':<10} {'META%':>6}  {'WR%':>5}  {'TREND':>8}  {'DECKS':>6}  {'PRICE':>6}")
    print("-" * 80)
    for d in meta:
        ms = d.get("meta_share") or 0.0
        wr = d.get("winrate") or 0.0
        price = d.get("price_paper") or 0
        print(
            f"{d.get('name', ''):<28} "
            f"{d.get('tier', ''):<10} "
            f"{ms:>5.2f}%  "
            f"{wr:>4.0f}%  "
            f"{d.get('trend', ''):>8}  "
            f"{d.get('decks', 0) or 0:>6}  "
            f"${price:>5}"
        )

    if args.winrates:
        print(f"\n\nWINRATE MATRIX ({len(output['winrates'])} decks)")
        for deck, matchups in output["winrates"].items():
            print(f"\n  {deck}")
            for opp, data in matchups.items():
                wr = data.get("winrate")
                m = data.get("matches")
                if wr is not None:
                    bar = "▓" if wr >= 50 else "░"
                    print(f"    vs {opp:<26} {wr:>5.1f}%  ({m or '?'} matches)  {bar}")


if __name__ == "__main__":
    main()
