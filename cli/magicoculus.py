from __future__ import annotations

import json

import typer

from cli.db import get_db
from core.config import settings
from services.magicoculus import (
    MagicOculusApiError,
    MagicOculusClient,
    MagicOculusCollectionError,
    MagicOculusImporter,
    MagicOculusTournamentCollector,
    magicoculus_city_for_club,
)

app = typer.Typer(no_args_is_help=True)


@app.command("preview")
def preview(tournament_id: int = typer.Argument(..., help="ID турнира MetaGatherer")) -> None:
    """Собрать и показать один импорт без отправки в Magic Oculus."""
    try:
        with get_db() as db:
            tournament = MagicOculusTournamentCollector(db).collect(tournament_id, validate_aetherhub=True)
    except MagicOculusCollectionError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(1) from exc

    payload = {
        "sourceTournamentId": tournament.source_tournament_id,
        "date": tournament.date.isoformat(),
        "club": tournament.club,
        "format": tournament.format,
        "tournamentType": tournament.tournament_type,
        "source": tournament.source_kind,
        "aetherhubUrl": str(tournament.aetherhub_url) if tournament.aetherhub_url else None,
        "finalStandingsCsv": tournament.final_standings_csv,
        "allRoundsCsv": tournament.all_rounds_csv,
        "players": len(tournament.player_decks),
        "playerDecksText": tournament.positional_player_decks_text,
        "playerDecksNamedPreview": tournament.player_decks_text,
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("send")
def send(
    tournament_id: int = typer.Argument(..., help="ID турнира MetaGatherer"),
    city: str | None = typer.Option(None, help="Город Oculus; по умолчанию берётся из настройки клуба"),
    execute: bool = typer.Option(False, "--execute", help="Подтвердить реальный POST"),
) -> None:
    """Отправить один турнир ровно один раз и записать результат в журнал."""
    if not execute:
        typer.echo("Отправка не выполнена: сначала preview, затем повтори с --execute", err=True)
        raise typer.Exit(2)
    try:
        with get_db() as db:
            tournament = MagicOculusTournamentCollector(db).collect(tournament_id, validate_aetherhub=True)
            client = MagicOculusClient(settings.MAGIC_OCULUS_API_URL)
            result = MagicOculusImporter(db, client).import_once(
                tournament,
                city=city or magicoculus_city_for_club(tournament.club),
            )
    except (MagicOculusCollectionError, MagicOculusApiError) as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"✓ Magic Oculus tournament #{result.tournament_id}")
    typer.echo(f"  {settings.MAGIC_OCULUS_PUBLIC_URL.rstrip('/')}/tournaments/{result.tournament_id}")
    for warning in result.warnings:
        typer.echo(f"  WARNING {warning.code}: {warning.message}")
