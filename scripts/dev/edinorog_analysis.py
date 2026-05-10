"""
Optimal deck selection for Edinorog club meta using global winrates.

Usage:
    python3 scripts/dev/edinorog_analysis.py
"""

import sys

sys.path.insert(0, ".")
from scripts.dev.mtgdecks_scraper import fetch_winrates

# ── Edinorog meta (tournament registrations) ─────────────────────────────────
EDINOROG_META = {
    "Grixis Affinity": 20,
    "Elves": 19,
    "Spy": 19,
    "Dimir Terror": 19,
    "White Weenie": 17,
    "Caw Gates": 16,
    "Blue Faeries": 15,
    "Rakdos Madness": 15,
    "Flicker Tron": 14,
    "Red Madness": 13,
    "Blue Delver": 13,
    "Jund Midrange": 10,
    "Dimir Faeries": 10,
    "Pizza Combo": 7,
    "Black Sacrifice": 6,
    "Red Rally": 6,
    "Orzhov Blade": 6,
    "Bogles": 5,
    "White Heroic": 5,
    "Combo Walls": 5,
    "Gruul Ramp": 4,
    "Poison Storm": 4,
    "Izzet Faeries": 4,
    "Gruul Ponza": 4,
    "Azorius Familiars": 4,
    "Green Tron": 3,
}

# Map local deck names → global archetype names (mtgdecks.net)
LOCAL_TO_GLOBAL = {
    "Grixis Affinity": "Grixis Affinity",
    "Elves": "Elves",
    "Spy": "Spy Combo",
    "Dimir Terror": "Dimir Terror",
    "White Weenie": "White Weenie",
    "Caw Gates": "Caw Gates",
    "Blue Faeries": "Mono Blue Faeries",
    "Rakdos Madness": "Rakdos Madness",
    "Flicker Tron": "Flicker Tron",
    "Red Madness": "Mono Red Madness",
    "Blue Delver": "Mono Blue Terror",
    "Jund Midrange": "Jund Wildfire",  # closest global equivalent
    "Dimir Faeries": "UB Faeries",
    "Pizza Combo": "Pizza Combo",
    "Black Sacrifice": "Mono Black Sacrifice",
    "Red Rally": "Mono Red Rally",
    "Orzhov Blade": "Orzhov Blade",
    "Bogles": "GW Bogles",
    "White Heroic": "Mono White Heroic",
    "Combo Walls": "Defender Combo",
    "Gruul Ramp": "Gruul Ramp",
    "Poison Storm": "Poison Storm",
    "Izzet Faeries": "Izzet Faeries",
    "Gruul Ponza": "Gruul Ponza",
    "Azorius Familiars": "UWx Familiar",
    "Green Tron": "Monster Tron",  # closest global equivalent
}

# Candidate decks to evaluate (global names)
CANDIDATES = [
    "Spy Combo",
    "Dimir Terror",
    "Elves",
    "Monster Tron",
    "Grixis Affinity",
    "Jund Wildfire",
    "White Weenie",
    "Mono Red Madness",
    "Caw Gates",
    "Orzhov Blade",
    "Naya Gates",
    "GW Bogles",
    "Red Storm",
    "UWx Familiar",
    "Mono Blue Terror",
]


def calculate_ev(candidate: str, matrix: dict, edinorog: dict, local_to_global: dict) -> dict:
    """
    Calculate expected winrate of `candidate` against Edinorog field.
    Uses global matchup data. Returns EV, coverage, and per-matchup details.
    """
    total_weight = sum(edinorog.values())
    matchup_data = matrix.get(candidate, {})

    ev_sum = 0.0
    covered_weight = 0.0
    details = []

    for local_deck, count in sorted(edinorog.items(), key=lambda x: -x[1]):
        global_opp = local_to_global.get(local_deck)
        weight = count / total_weight
        wr = None

        if global_opp and global_opp in matchup_data:
            cell = matchup_data[global_opp]
            wr = cell.get("winrate")
            matches = cell.get("matches")
        else:
            matches = None

        if wr is not None:
            ev_sum += weight * wr
            covered_weight += weight
            details.append(
                {
                    "opponent": local_deck,
                    "global_name": global_opp or "?",
                    "weight": weight * 100,
                    "winrate": wr,
                    "matches": matches,
                }
            )

    coverage = covered_weight
    if coverage > 0:
        ev_covered = ev_sum / covered_weight
        # uncovered portion assumed ~50%
        ev_total = ev_sum + 50.0 * (1 - covered_weight)
    else:
        ev_covered = 50.0
        ev_total = 50.0

    return {
        "candidate": candidate,
        "ev_covered": round(ev_covered, 1),
        "ev_total": round(ev_total, 1),
        "coverage": round(coverage * 100, 1),
        "details": details,
    }


def print_detail(result: dict):
    d = result
    print(f"\n{'=' * 62}")
    print(f"  {d['candidate']}")
    print(
        f"  EV vs covered field: {d['ev_covered']}%  |  Projected EV: {d['ev_total']}%  |  Coverage: {d['coverage']}%"
    )
    print(f"{'=' * 62}")
    print(f"  {'Opponent':<22} {'Field%':>7}  {'WR%':>6}  {'Matches':>8}  {'Bar'}")
    print(f"  {'-' * 58}")
    for m in sorted(d["details"], key=lambda x: -x["weight"]):
        bar = "▓" if m["winrate"] >= 55 else ("░" if m["winrate"] < 45 else "·")
        suffix = " ⚠" if m["winrate"] < 35 else ""
        print(
            f"  {m['opponent']:<22} {m['weight']:>6.1f}%  {m['winrate']:>5.0f}%  "
            f"{str(m['matches'] or '?'):>8}  {bar}{suffix}"
        )


def main():
    print("Fetching global matchup matrix from mtgdecks.net...", file=sys.stderr)
    matrix = fetch_winrates()
    print(f"Got {len(matrix)} decks in global matrix.\n", file=sys.stderr)

    results = []
    for candidate in CANDIDATES:
        if candidate not in matrix:
            print(f"  WARNING: '{candidate}' not in global matrix — skipping", file=sys.stderr)
            continue
        r = calculate_ev(candidate, matrix, EDINOROG_META, LOCAL_TO_GLOBAL)
        results.append(r)

    results.sort(key=lambda x: -x["ev_total"])

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "█" * 62)
    print("  OPTIMAL DECK FOR EDINOROG META  (global WR-based)")
    print("█" * 62)

    total_entries = sum(EDINOROG_META.values())
    print(
        f"\n  Field: {total_entries} registrations. Top 13 = "
        f"{sum(list(EDINOROG_META.values())[:13]) / total_entries * 100:.0f}% of meta."
    )

    print(f"\n  {'#':<3} {'Deck':<24} {'EV (covered)':>13}  {'EV (projected)':>15}  {'Coverage':>9}")
    print(f"  {'-' * 68}")
    for i, r in enumerate(results, 1):
        flag = " ← PICK" if i <= 3 else ""
        print(
            f"  {i:<3} {r['candidate']:<24} {r['ev_covered']:>12.1f}%  "
            f"{r['ev_total']:>14.1f}%  {r['coverage']:>8.1f}%{flag}"
        )

    # ── Meta field breakdown ─────────────────────────────────────────────────
    print("\n\n  EDINOROG FIELD vs GLOBAL META")
    print(f"  {'Deck':<22} {'Entries':>8}  {'Field%':>7}  {'Global equiv':<22}")
    print(f"  {'-' * 65}")
    for local, count in sorted(EDINOROG_META.items(), key=lambda x: -x[1])[:16]:
        share = count / total_entries * 100
        glob = LOCAL_TO_GLOBAL.get(local, "???")
        print(f"  {local:<22} {count:>8}  {share:>6.1f}%  {glob:<22}")

    # ── Per-deck detail ──────────────────────────────────────────────────────
    print("\n\n" + "─" * 62)
    print("  DETAILED MATCHUP BREAKDOWN (top 6 candidates)")
    for r in results[:6]:
        print_detail(r)

    # ── Key insights ─────────────────────────────────────────────────────────
    print(f"\n\n{'=' * 62}")
    print("  KEY INSIGHTS FOR EDINOROG")
    print(f"{'=' * 62}")

    # Find best and worst matchup per top deck
    for r in results[:4]:
        best = max(r["details"], key=lambda x: x["winrate"])
        worst = min(r["details"], key=lambda x: x["winrate"])
        print(f"\n  {r['candidate']}  (EV {r['ev_total']:.1f}%)")
        print(f"    Best:  vs {best['opponent']:<20} {best['winrate']:.0f}%  ({best['matches']}m)")
        print(f"    Worst: vs {worst['opponent']:<20} {worst['winrate']:.0f}%  ({worst['matches']}m)")


if __name__ == "__main__":
    main()
