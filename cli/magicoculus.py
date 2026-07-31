from __future__ import annotations

import json

import typer

from cli.db import get_db
from services.magicoculus import MagicOculusCollectionError, MagicOculusTournamentCollector

app = typer.Typer(no_args_is_help=True)


@app.command("preview")
def preview(tournament_id: int = typer.Argument(..., help="ID турнира MetaGatherer")) -> None:
    """Собрать и показать один импорт без отправки в Magic Oculus."""
    try:
        with get_db() as db:
            tournament = MagicOculusTournamentCollector(db).collect(tournament_id)
    except MagicOculusCollectionError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(1) from exc

    payload = {
        "sourceTournamentId": tournament.source_tournament_id,
        "date": tournament.date.isoformat(),
        "club": tournament.club,
        "format": tournament.format,
        "tournamentType": tournament.tournament_type,
        "aetherhubUrl": str(tournament.aetherhub_url),
        "players": len(tournament.player_decks),
        "playerDecksText": tournament.player_decks_text,
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
