#!/usr/bin/env python3
"""Read-only MetaGatherer/Oculus diagnostic for one tournament."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from core import models
from core.database import SessionLocal
from services.aetherhub_service import AetherhubService
from services.names import format_participant_name


def name_key(name: str) -> tuple[str, ...]:
    return tuple(sorted(name.strip().casefold().replace("ё", "е").split()))


def keyed(names: Iterable[str]) -> dict[tuple[str, ...], str]:
    return {name_key(name): name for name in names if name and name.upper() != "BYE"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tournament_id", type=int)
    parser.add_argument("--fetch-aetherhub", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tournament = db.get(models.Tournament, args.tournament_id)
        if tournament is None:
            raise SystemExit(f"Tournament #{args.tournament_id} not found")

        participants = sorted(
            tournament.participants,
            key=lambda row: (row.final_place is None, row.final_place or 0, row.id),
        )
        bot_names = [format_participant_name(row.user.first_name, row.user.last_name).strip() for row in participants]
        journal = (
            db.query(models.MagicOculusImport)
            .filter(models.MagicOculusImport.tournament_id == tournament.id)
            .order_by(models.MagicOculusImport.id)
            .all()
        )
        result = {
            "tournament": {
                "id": tournament.id,
                "title": tournament.title,
                "club": tournament.club,
                "status": getattr(tournament.status, "value", str(tournament.status)),
                "aetherhub_url": tournament.aetherhub_url,
            },
            "participants": [
                {
                    "participant_id": row.id,
                    "place": row.final_place,
                    "name": name,
                    "deck": row.archetype.name if row.archetype else None,
                    "placeholder": row.user.tg_id < 0,
                }
                for row, name in zip(participants, bot_names)
            ],
            "journal": [
                {
                    "id": row.id,
                    "status": row.status,
                    "magicoculus_tournament_id": row.magicoculus_tournament_id,
                    "has_error": bool(row.error_json),
                    "has_warnings": bool(row.warnings_json),
                }
                for row in journal
            ],
        }

        if args.fetch_aetherhub:
            if not tournament.aetherhub_url:
                raise SystemExit("Tournament has no AetherHub URL")
            source = AetherhubService().fetch_tournament(tournament.aetherhub_url)
            players = [name for name in source.players if name.upper() != "BYE"]
            standings = [name for name in source.standings if name.upper() != "BYE"]
            bot_map, players_map, standings_map = keyed(bot_names), keyed(players), keyed(standings)
            result["aetherhub"] = {
                "players_count": len(players),
                "standings_count": len(standings),
                "rounds_count": len([row for row in source.rounds if row.pairings]),
                "players_not_in_bot": sorted(players_map[key] for key in players_map.keys() - bot_map.keys()),
                "standings_not_in_bot": sorted(
                    standings_map[key] for key in standings_map.keys() - bot_map.keys()
                ),
                "bot_not_in_standings": sorted(
                    bot_map[key] for key in bot_map.keys() - standings_map.keys()
                ),
            }

        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
