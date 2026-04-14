"""
Merge player lists from two Telegram chats, resolve names to Russian,
fetch deck stats from DataLens, and produce a combined table.

Usage:
    python3 scripts/merge_and_fetch.py [--dry-run] [--output results.csv]

Options:
    --dry-run       Parse and match names, skip DataLens requests
    --output FILE   Save results to CSV file (default: print to stdout)
    --mapping FILE  Path to manual name mapping JSON (default: scripts/name_mapping.json)
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).parent
TELEGRAM_DIR = SCRIPTS_DIR / "telegram_parser"
DATALENS_DIR = SCRIPTS_DIR / "datalens_parser"

PLAYERS_FILE_1 = TELEGRAM_DIR / "players.txt"
PLAYERS_FILE_2 = TELEGRAM_DIR / "players_edinorog.txt"
DATALENS_PLAYERS_JSON = DATALENS_DIR / "players_list_response.json"
DEFAULT_MAPPING_FILE = SCRIPTS_DIR / "name_mapping.json"

# ---------------------------------------------------------------------------
# Step 1: Parse Telegram player files
# ---------------------------------------------------------------------------

# Each data line looks like:
#   Mikhail Babaev                           @mbabaev                  232778570
# Fields are separated by 2+ spaces.
_DATA_LINE_RE = re.compile(r"^(.+?)\s{2,}(@\S+|\(no username\))\s{2,}(\d+)\s*$")


def _parse_player_line(line: str) -> tuple[str, str, int] | None:
    """Return (name, username, tg_id) or None if the line is not a data row."""
    m = _DATA_LINE_RE.match(line)
    if not m:
        return None
    name = m.group(1).strip()
    username = m.group(2).strip()
    tg_id = int(m.group(3))
    return name, username, tg_id


def parse_players_file(path: Path) -> list[tuple[str, str, int]]:
    """Parse a players.txt file and return list of (name, username, tg_id)."""
    results = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parsed = _parse_player_line(line.rstrip("\n"))
            if parsed:
                results.append(parsed)
    return results


def merge_and_dedup(
    list1: list[tuple[str, str, int]],
    list2: list[tuple[str, str, int]],
) -> list[tuple[str, str, int]]:
    """Merge two player lists, deduplicating by tg_id. list1 takes priority."""
    seen: dict[int, tuple[str, str, int]] = {}
    for entry in list1 + list2:
        _, _, tg_id = entry
        if tg_id not in seen:
            seen[tg_id] = entry
    return list(seen.values())


# ---------------------------------------------------------------------------
# Step 2: Resolve names to Russian
# ---------------------------------------------------------------------------

def _is_cyrillic(text: str) -> bool:
    return bool(re.search(r"[а-яёА-ЯЁ]", text))


def load_datalens_names(path: Path) -> list[str]:
    """Load the list of Russian player names from the DataLens selector response."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    content = data.get("uiScheme", [{}])[0].get("content", [])
    return [
        item["value"]
        for item in content
        if item.get("value") and item["value"] != "NO_LEGAL_NAME"
    ]


def load_manual_mapping(path: Path) -> dict[str, str]:
    """Load optional manual name mapping: {"English Name": "Русское Имя"}."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _name_candidates(name: str) -> list[str]:
    """
    Generate lookup variants for a name:
    - original order
    - reversed word order (Имя Фамилия ↔ Фамилия Имя)
    - if Latin: transliterated versions of both orders
    """
    from transliterate import translit as _translit

    parts = name.strip().split()
    variants = [name]
    if len(parts) == 2:
        variants.append(" ".join(reversed(parts)))

    if not _is_cyrillic(name):
        try:
            tlit = _translit(name, "ru")
            tlit_parts = tlit.strip().split()
            variants.append(tlit)
            if len(tlit_parts) == 2:
                variants.append(" ".join(reversed(tlit_parts)))
        except Exception:  # noqa: BLE001
            pass

    return variants


def resolve_names(
    players: list[tuple[str, str, int]],
    datalens_names: list[str],
    manual_mapping: dict[str, str],
) -> list[dict]:
    """
    For each player resolve their name to a Russian DataLens name.

    Returns list of dicts with keys:
        tg_id, tg_name, username, ru_name, match_score, status
    Status values: 'cyrillic' | 'manual' | 'fuzzy_ok' | 'fuzzy_low' | 'not_found'
    """
    from rapidfuzz import process, fuzz

    results = []

    for name, username, tg_id in players:
        row = {
            "tg_id": tg_id,
            "tg_name": name,
            "username": username,
            "ru_name": "",
            "match_score": None,
            "status": "",
        }

        # 1. Manual override
        if name in manual_mapping:
            row["ru_name"] = manual_mapping[name]
            row["status"] = "manual"
            results.append(row)
            continue

        # 2. Exact match (handles already-correct Cyrillic names)
        if name in datalens_names:
            row["ru_name"] = name
            row["match_score"] = 100
            row["status"] = "cyrillic"
            results.append(row)
            continue

        # 3. Fuzzy match across all candidate variants (handles word order + transliteration)
        best_ru_name = ""
        best_score = 0.0
        for candidate in _name_candidates(name):
            match = process.extractOne(candidate, datalens_names, scorer=fuzz.WRatio)
            if match and match[1] > best_score:
                best_score = match[1]
                best_ru_name = match[0]

        if best_ru_name:
            row["ru_name"] = best_ru_name
            row["match_score"] = round(best_score, 1)
            row["status"] = "fuzzy_ok" if best_score >= 85 else "fuzzy_low"
        else:
            row["status"] = "not_found"

        results.append(row)

    return results


# ---------------------------------------------------------------------------
# Step 3: Fetch DataLens deck stats
# ---------------------------------------------------------------------------

def fetch_all_stats(resolved: list[dict], dry_run: bool = False) -> list[dict]:
    """
    Add 'decks' key to each resolved player row.
    'decks' is a list of DeckStats objects (or empty list if no data / not_found).
    """
    sys.path.insert(0, str(DATALENS_DIR))
    from datalens_player_stats import fetch_player_stats  # noqa: PLC0415

    for i, row in enumerate(resolved):
        ru_name = row.get("ru_name", "")
        if not ru_name or row["status"] == "not_found":
            row["decks"] = []
            continue

        if dry_run:
            row["decks"] = []
            continue

        try:
            decks = fetch_player_stats(ru_name)
            row["decks"] = decks
            print(f"  [{i+1}/{len(resolved)}] {ru_name}: {len(decks)} колод(ы)", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i+1}/{len(resolved)}] ERROR for {ru_name!r}: {exc}", file=sys.stderr)
            row["decks"] = []

    return resolved


# ---------------------------------------------------------------------------
# Step 4: Output
# ---------------------------------------------------------------------------

def format_decks(decks: list) -> str:
    """Format deck list as a comma-separated string of names."""
    return ", ".join(d.name for d in decks) if decks else ""


def print_table(rows: list[dict]) -> None:
    """Print results as a human-readable table to stdout."""
    col_id = 12
    col_name = 30
    col_decks = 60

    header = f"{'tg_id':<{col_id}} {'Имя (RU)':<{col_name}} {'Колоды':<{col_decks}}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{str(row['tg_id']):<{col_id}} "
            f"{row.get('ru_name', row['tg_name']):<{col_name}} "
            f"{format_decks(row['decks']):<{col_decks}}"
        )

    # Print review list
    needs_review = [r for r in rows if r["status"] in ("fuzzy_low", "not_found")]
    if needs_review:
        print(f"\n--- Требуют проверки ({len(needs_review)}) ---")
        for r in needs_review:
            print(
                f"  [{r['status']}] tg={r['tg_id']} tg_name={r['tg_name']!r} "
                f"→ ru={r.get('ru_name', '?')!r} score={r.get('match_score')}"
            )


def write_csv(rows: list[dict], path: Path) -> None:
    """Write results to a CSV file."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["tg_id", "ru_name", "tg_name", "username", "status", "match_score", "decks"])
        for row in rows:
            writer.writerow([
                row["tg_id"],
                row.get("ru_name", ""),
                row["tg_name"],
                row["username"],
                row["status"],
                row.get("match_score", ""),
                format_decks(row["decks"]),
            ])
    print(f"Saved to {path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Skip DataLens requests")
    parser.add_argument("--output", metavar="FILE", help="Save results to CSV")
    parser.add_argument("--mapping", metavar="FILE", default=str(DEFAULT_MAPPING_FILE),
                        help="Path to manual name mapping JSON")
    args = parser.parse_args()

    # Step 1
    print("Step 1: Parsing Telegram player files...", file=sys.stderr)
    list1 = parse_players_file(PLAYERS_FILE_1)
    list2 = parse_players_file(PLAYERS_FILE_2)
    merged = merge_and_dedup(list1, list2)
    print(f"  {len(list1)} + {len(list2)} → {len(merged)} unique players", file=sys.stderr)

    # Step 2
    print("Step 2: Resolving names to Russian...", file=sys.stderr)
    datalens_names = load_datalens_names(DATALENS_PLAYERS_JSON)
    manual_mapping = load_manual_mapping(Path(args.mapping))
    resolved = resolve_names(merged, datalens_names, manual_mapping)

    statuses = {}
    for r in resolved:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    print(f"  Status breakdown: {statuses}", file=sys.stderr)

    # Step 3
    if args.dry_run:
        print("Step 3: Skipping DataLens (--dry-run)", file=sys.stderr)
    else:
        print(f"Step 3: Fetching DataLens stats for {len(resolved)} players...", file=sys.stderr)
    fetch_all_stats(resolved, dry_run=args.dry_run)

    # Step 4
    print("Step 4: Output", file=sys.stderr)
    if args.output:
        write_csv(resolved, Path(args.output))
    else:
        print_table(resolved)


if __name__ == "__main__":
    main()
