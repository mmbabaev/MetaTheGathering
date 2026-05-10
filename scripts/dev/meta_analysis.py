"""
Pauper meta analysis: global vs Moscow local meta.
Goal: find the optimal deck for the local metagame.

Usage:
    python3 scripts/dev/meta_analysis.py
"""

# ── Local meta: deck appearances (tournament registrations) ──────────────────
LOCAL_META_SHARE = {
    "Red Madness": 43,
    "Jund Midrange": 43,
    "Rakdos Madness": 42,
    "Grixis Affinity": 42,
    "Dimir Terror": 39,
    "White Weenie": 37,
    "Spy": 36,
    "Blue Delver": 35,
    "Flicker Tron": 32,
    "Elves": 31,
    "Blue Faeries": 31,
    "Caw Gates": 31,
    "Dimir Faeries": 23,
    "Orzhov Blade": 18,
    "Green Tron": 17,
    "Red Rally": 17,
    "Black Sacrifice": 16,
    "Gruul Ramp": 15,
    "Gardens": 13,
    "Poison Storm": 13,
    "White Heroic": 13,
    "Pizza Combo": 13,
    "Gruul Ponza": 12,
    "Bogles": 11,
    "Azorius Familiars": 11,
    "Combo Walls": 10,
    "Izzet Faeries": 9,
    "Rogue": 7,
    "Dimir Affinity": 7,
    "Dimir Control": 7,
    "Combo Affinity": 6,
    "Pinger Burn": 6,
    "Dimir Exhume": 6,
    "Altar Tron": 5,
    "Turbo Fog": 5,
    "Esper Affinity": 5,
}

# ── Local meta: overall winrates by deck (matches >= 40) ─────────────────────
LOCAL_WINRATES = {
    "Red Madness": (195, 50.7),
    "Rakdos Madness": (173, 45.9),
    "Grixis Affinity": (169, 50.3),
    "Jund Midrange": (168, 52.9),
    "Dimir Terror": (158, 57.8),
    "Blue Delver": (156, 48.3),
    "Spy": (152, 55.2),
    "White Weenie": (149, 48.7),
    "Flicker Tron": (137, 51.7),
    "Caw Gates": (127, 47.4),
    "Elves": (124, 53.2),
    "Blue Faeries": (122, 53.0),
    "Dimir Faeries": (93, 49.5),
    "Orzhov Blade": (75, 56.7),
    "Gruul Ramp": (70, 54.3),
    "Black Sacrifice": (67, 50.5),
    "Red Rally": (67, 50.2),
    "Green Tron": (61, 55.5),
    "Gardens": (52, 47.4),
    "Pizza Combo": (52, 51.0),
    "Gruul Ponza": (51, 59.2),
    "Poison Storm": (50, 52.0),
    "Bogles": (46, 46.0),
    "White Heroic": (46, 41.3),
    "Combo Walls": (44, 59.1),
    "Azorius Familiars": (42, 48.4),
}

# ── Local matchup matrices (deck → {opponent: (matches, winrate%)}) ──────────
# Source: per-deck "Opponent decks" exports; only opponents with ≥4 matches kept

LOCAL_MATCHUPS = {
    "Red Madness": {
        "Blue Delver": (18, 50.0),
        "Jund Midrange": (16, 54.2),
        "Elves": (14, 72.6),
        "Red Madness": (14, 50.0),
        "Grixis Affinity": (11, 42.4),
        "Blue Faeries": (10, 40.0),
        "Rakdos Madness": (9, 25.9),
        "Black Sacrifice": (7, 47.6),
        "Dimir Terror": (7, 47.6),
        "Flicker Tron": (6, 47.2),
        "Spy": (6, 52.8),
        "Bogles": (5, 33.3),
        "Azorius Familiars": (4, 25.0),
        "Caw Gates": (4, 45.8),
        "Dimir Affinity": (4, 33.3),
        "Dimir Faeries": (4, 58.3),
        "Gruul Ramp": (4, 58.3),
        "Orzhov Blade": (4, 25.0),
        "Red Rally": (4, 91.7),
        "White Weenie": (4, 50.0),
    },
    "Rakdos Madness": {
        "Caw Gates": (13, 34.6),
        "Jund Midrange": (12, 38.9),
        "Blue Delver": (10, 60.0),
        "Elves": (9, 29.6),
        "Red Madness": (9, 74.1),
        "Dimir Terror": (8, 16.7),
        "White Weenie": (8, 50.0),
        "Grixis Affinity": (7, 31.0),
        "Rakdos Madness": (6, 50.0),
        "Spy": (6, 38.9),
        "Flicker Tron": (5, 40.0),
        "Poison Storm": (5, 33.3),
        "White Heroic": (5, 60.0),
        "Black Sacrifice": (4, 33.3),
        "Blue Faeries": (4, 29.2),
        "Combo Walls": (4, 25.0),
        "Orzhov Blade": (4, 75.0),
        "Gardens": (3, 66.7),
        "Green Tron": (3, 22.2),
        "Gruul Ramp": (3, 22.2),
    },
    "Grixis Affinity": {
        "Dimir Terror": (11, 34.8),
        "Red Madness": (11, 57.6),
        "Spy": (11, 51.5),
        "Dimir Faeries": (9, 53.7),
        "Caw Gates": (8, 47.9),
        "Elves": (8, 41.7),
        "Grixis Affinity": (8, 50.0),
        "White Weenie": (8, 16.7),
        "Blue Delver": (7, 42.9),
        "Flicker Tron": (7, 33.3),
        "Jund Midrange": (7, 42.9),
        "Rakdos Madness": (7, 69.0),
        "Poison Storm": (5, 13.3),
        "Blue Faeries": (4, 75.0),
        "Gardens": (4, 58.3),
        "Pizza Combo": (4, 50.0),
        "Gruul Ramp": (3, 66.7),
        "Orzhov Blade": (3, 50.0),
        "White Heroic": (3, 22.2),
    },
    "Jund Midrange": {
        "Red Madness": (16, 45.8),
        "Dimir Terror": (12, 30.6),
        "Flicker Tron": (12, 45.8),
        "Rakdos Madness": (12, 61.1),
        "Blue Faeries": (11, 72.7),
        "White Weenie": (11, 60.6),
        "Jund Midrange": (8, 50.0),
        "Black Sacrifice": (7, 69.0),
        "Blue Delver": (7, 66.7),
        "Grixis Affinity": (7, 57.1),
        "Azorius Familiars": (6, 44.4),
        "Caw Gates": (6, 55.6),
        "Orzhov Blade": (5, 56.7),
        "Spy": (5, 46.7),
        "Green Tron": (4, 50.0),
    },
    "Dimir Terror": {
        "Flicker Tron": (16, 66.7),
        "Jund Midrange": (12, 69.4),
        "Grixis Affinity": (11, 65.2),
        "Spy": (11, 54.5),
        "Blue Delver": (10, 56.7),
        "Orzhov Blade": (8, 45.8),
        "Rakdos Madness": (8, 83.3),
        "White Weenie": (8, 66.7),
        "Red Madness": (7, 52.4),
        "Blue Faeries": (6, 33.3),
        "Dimir Faeries": (6, 47.2),
        "Caw Gates": (5, 80.0),
        "Elves": (4, 41.7),
        "Red Rally": (3, 27.8),
        "White Heroic": (3, 55.6),
        "Combo Walls": (3, 55.6),
    },
    "Blue Delver": {
        "Red Madness": (18, 50.0),
        "Dimir Terror": (10, 43.3),
        "Rakdos Madness": (10, 40.0),
        "Blue Faeries": (8, 60.4),
        "Spy": (8, 37.5),
        "Grixis Affinity": (7, 57.1),
        "Jund Midrange": (7, 33.3),
        "Blue Delver": (6, 50.0),
        "Caw Gates": (6, 55.6),
        "Flicker Tron": (6, 38.9),
        "Dimir Faeries": (5, 46.7),
        "Elves": (5, 46.7),
        "Gardens": (4, 83.3),
        "Gruul Ponza": (4, 33.3),
        "Red Rally": (4, 50.0),
        "White Heroic": (4, 50.0),
        "Azorius Familiars": (3, 27.8),
        "Bogles": (3, 55.6),
        "Orzhov Blade": (3, 77.8),
    },
    "Spy": {
        "Dimir Terror": (11, 45.5),
        "Grixis Affinity": (11, 48.5),
        "Flicker Tron": (10, 46.7),
        "Blue Delver": (8, 62.5),
        "Blue Faeries": (8, 50.0),
        "Spy": (8, 50.0),
        "Elves": (7, 33.3),
        "Dimir Faeries": (6, 30.6),
        "Gruul Ramp": (6, 61.1),
        "Rakdos Madness": (6, 61.1),
        "Red Madness": (6, 47.2),
        "Black Sacrifice": (5, 46.7),
        "Caw Gates": (5, 63.3),
        "Gardens": (5, 40.0),
        "Jund Midrange": (5, 53.3),
        "White Weenie": (5, 76.7),
        "Izzet Faeries": (4, 50.0),
        "Bogles": (3, 77.8),
        "Combo Walls": (3, 66.7),
    },
}

# ── Global meta reference (moxfield/mtgdecks, Tier-1/2 only) ─────────────────
# Format: {deck: (meta_share%, winrate%)}
GLOBAL_META = {
    "Mono Red Madness": (10.44, 52),
    "Grixis Affinity": (7.67, 51),
    "Elves": (5.95, 52),
    "Jund Wildfire": (5.11, 50),
    "White Weenie": (4.96, 52),
    "Dimir Terror": (4.65, 50),
    "Mono Blue Terror": (4.59, 46),
    "Gruul Ramp": (3.63, 50),
    "Golgari Gardens": (3.60, 51),
    "Rakdos Madness": (3.34, 47),
    "Mono Red Rally": (3.30, 47),
    "Spy Combo": (3.23, 56),
    "Monster Tron": (2.30, 53),
    "Caw Gates": (2.23, 51),
    "Orzhov Blade": (2.08, 48),
    "UB Faeries": (2.02, 47),
    "UWX Familiar": (1.95, 53),
    "Mono Blue Faeries": (1.76, 52),
    "Jeskai Ephemerate": (1.41, 51),
    "Mono Black Sacrifice": (1.38, 49),
    "Izzet Skred": (1.30, 52),
    "Red Storm": (1.25, 57),
    "GW Bogles": (1.10, 50),
    "Altar Tron": (1.03, 53),
    "Naya Gates": (0.93, 60),
}

# ── Global matchup matrix (abbreviated — key matchups only) ──────────────────
# Format: {deck: {opponent: winrate%}}  (from mtgdecks.net table)
GLOBAL_MATCHUPS = {
    "Mono Red Madness": {
        "Grixis Affinity": 50,
        "Elves": 46,
        "Jund Wildfire": 74,
        "White Weenie": 57,
        "Dimir Terror": 42,
        "Mono Blue Terror": 41,
        "Rakdos Madness": 41,
        "Spy Combo": 54,
        "Mono Red Rally": 46,
        "Gruul Ramp": 33,
        "Golgari Gardens": 60,
    },
    "Grixis Affinity": {
        "Mono Red Madness": 54,
        "Elves": 62,
        "Jund Wildfire": 38,
        "White Weenie": 64,
        "Dimir Terror": 47,
        "Mono Blue Terror": 36,
        "Rakdos Madness": 53,
        "Spy Combo": 47,
        "Mono Red Rally": 62,
        "Gruul Ramp": 53,
        "Golgari Gardens": 57,
    },
    "Elves": {
        "Mono Red Madness": 26,
        "Grixis Affinity": 50,
        "Jund Wildfire": 57,
        "White Weenie": 66,
        "Dimir Terror": 45,
        "Mono Blue Terror": 34,
        "Rakdos Madness": 56,
        "Spy Combo": 51,
        "Mono Red Rally": 61,
        "Gruul Ramp": 69,
        "Golgari Gardens": 51,
    },
    "Dimir Terror": {
        "Mono Red Madness": 54,
        "Grixis Affinity": 47,
        "Elves": 55,
        "Jund Wildfire": 57,
        "White Weenie": 52,
        "Mono Blue Terror": 70,
        "Rakdos Madness": 48,
        "Spy Combo": 52,
        "Mono Red Rally": 35,
        "Gruul Ramp": 48,
        "Golgari Gardens": 50,
    },
    "Spy Combo": {
        "Mono Red Madness": 46,
        "Grixis Affinity": 53,
        "Elves": 49,
        "Jund Wildfire": 53,
        "White Weenie": 61,
        "Dimir Terror": 50,
        "Mono Blue Terror": 56,
        "Rakdos Madness": 72,
        "Mono Red Rally": 81,
        "Gruul Ramp": 70,
        "Golgari Gardens": 40,
    },
}


def weighted_ev(deck: str, local_shares: dict, local_matchups: dict) -> dict:
    """
    Calculate expected winrate of `deck` against local field,
    using local matchup data where available.
    Returns dict with: ev, coverage (fraction of field covered), details.
    """
    matchups = local_matchups.get(deck, {})
    total_weight = sum(local_shares.values())
    covered_weight = 0.0
    ev_sum = 0.0
    details = []

    for opp, opp_count in sorted(local_shares.items(), key=lambda x: -x[1]):
        w = opp_count / total_weight
        if opp in matchups:
            m, wr = matchups[opp]
            ev_sum += w * wr
            covered_weight += w
            details.append((opp, w * 100, wr, m))

    coverage = covered_weight
    # Normalize EV to covered portion (then extrapolate assuming ~50% for rest)
    if coverage > 0:
        ev_covered = ev_sum / covered_weight
        ev_total = ev_covered * coverage + 50.0 * (1 - coverage)
    else:
        ev_covered = 50.0
        ev_total = 50.0

    return {
        "deck": deck,
        "ev_covered": round(ev_covered, 1),
        "ev_total": round(ev_total, 1),
        "coverage": round(coverage * 100, 1),
        "details": details,
    }


def print_matchup_table(deck: str, result: dict):
    print(f"\n{'=' * 60}")
    print(f"  {deck}  |  EV vs covered field: {result['ev_covered']}%  |  Coverage: {result['coverage']}%")
    print(f"  Projected EV vs full field: {result['ev_total']}%")
    print(f"{'=' * 60}")
    print(f"  {'Opponent':<22} {'Field%':>7}  {'WR%':>6}  {'Matches':>7}")
    print(f"  {'-' * 50}")
    for opp, w, wr, m in sorted(result["details"], key=lambda x: -x[1]):
        bar = "▓" if wr >= 50 else "░"
        print(f"  {opp:<22} {w:>6.1f}%  {wr:>5.1f}%  {m:>5}m  {bar}")


def main():
    print("\n" + "█" * 60)
    print("  PAUPER MOSCOW META — OPTIMAL DECK ANALYSIS")
    print("  " + "2026-05-02")
    print("█" * 60)

    # 1. Local meta overview
    total_entries = sum(LOCAL_META_SHARE.values())
    print(f"\n📊 LOCAL META (top decks by registrations, total={total_entries})")
    print(f"  {'Deck':<22} {'Entries':>8}  {'Share%':>7}  {'WR%':>7}  {'Matches':>8}")
    print(f"  {'-' * 60}")
    for deck, count in sorted(LOCAL_META_SHARE.items(), key=lambda x: -x[1])[:20]:
        share = count / total_entries * 100
        wr_info = LOCAL_WINRATES.get(deck)
        if wr_info:
            m, wr = wr_info
            wr_str = f"{wr:5.1f}%"
            m_str = f"{m:5}m"
        else:
            wr_str = "  n/a"
            m_str = "  n/a"
        diff = (wr_info[1] - 50) if wr_info else 0
        arrow = "↑" if diff > 2 else ("↓" if diff < -2 else "→")
        print(f"  {deck:<22} {count:>8}  {share:>6.1f}%  {wr_str}  {m_str}  {arrow}")

    # 2. EV analysis for decks with local matchup data
    print("\n📈 EXPECTED VALUE vs LOCAL FIELD (decks with matchup data)")
    results = []
    for deck in LOCAL_MATCHUPS:
        r = weighted_ev(deck, LOCAL_META_SHARE, LOCAL_MATCHUPS)
        results.append(r)
    results.sort(key=lambda x: -x["ev_covered"])

    print(f"\n  {'Deck':<22} {'EV (covered)':>13}  {'EV (projected)':>15}  {'Coverage':>9}")
    print(f"  {'-' * 65}")
    for r in results:
        print(f"  {r['deck']:<22} {r['ev_covered']:>12.1f}%  {r['ev_total']:>14.1f}%  {r['coverage']:>8.1f}%")

    # 3. Detailed matchup tables
    for r in results:
        print_matchup_table(r["deck"], r)

    # 4. Global vs local comparison
    print(f"\n\n{'=' * 60}")
    print("  GLOBAL vs LOCAL — META DIVERGENCE")
    print(f"{'=' * 60}")
    mappings = [
        ("Red Madness", "Mono Red Madness", 10.44, 52),
        ("Rakdos Madness", "Rakdos Madness", 3.34, 47),
        ("Grixis Affinity", "Grixis Affinity", 7.67, 51),
        ("Dimir Terror", "Dimir Terror", 4.65, 50),
        ("Spy", "Spy Combo", 3.23, 56),
        ("White Weenie", "White Weenie", 4.96, 52),
        ("Caw Gates", "Caw Gates", 2.23, 51),
        ("Elves", "Elves", 5.95, 52),
        ("Blue Delver", "Mono Blue Terror", 4.59, 46),
        ("Flicker Tron", "Flicker Tron", 0.0, 50),  # not in global top
        ("Blue Faeries", "Mono Blue Faeries", 1.76, 52),
    ]
    print(f"\n  {'Local deck':<22} {'Local WR':>9}  {'Global equiv':<20} {'Global WR':>10}  {'ΔWR':>5}")
    print(f"  {'-' * 75}")
    for local, glob, gshare, gwr in mappings:
        linfo = LOCAL_WINRATES.get(local)
        if linfo:
            lm, lwr = linfo
            delta = lwr - gwr
            arrow = f"+{delta:.1f}" if delta > 0 else f"{delta:.1f}"
            print(f"  {local:<22} {lwr:>8.1f}%  {glob:<20} {gwr:>9}%  {arrow:>5}")

    # 5. Recommendations
    print(f"\n\n{'=' * 60}")
    print("  RECOMMENDATIONS")
    print(f"{'=' * 60}")
    print("""
  KEY LOCAL META FACTS:
  • Flicker Tron is huge locally (32 entries) — nearly absent globally
  • Jund Midrange (local) ≠ Jund Wildfire (global) — different deck
  • Rakdos Madness massively underperforms locally (45.9% vs 47% global)
  • Dimir Terror overperforms locally (57.8% vs 50% global)
  • Blue Delver (≈ Mono Blue Terror) at 48.3% — similar to global (46%)

  BEST BETS FOR LOCAL META (by EV vs covered field):
  1. Dimir Terror  — beats most top local decks hard; weak vs Blue Faeries
  2. Spy           — consistent; white weenie matchup is a bonus locally
  3. Jund Midrange — great vs aggro; struggles vs Dimir Terror (30%)

  AVOID:
  • Rakdos Madness — terrible vs Dimir Terror (17%), Elves (30%), Caw Gates (35%)
  • Grixis Affinity — White Weenie matchup 17%, Poison Storm 13%
    """)


if __name__ == "__main__":
    main()
