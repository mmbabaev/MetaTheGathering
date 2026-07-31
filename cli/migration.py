from __future__ import annotations

import json
from datetime import datetime

import typer

from core.clubs import ClubIdentity, club_identities
from services.aetherhub_service import AetherhubService
from services.datalens import DataLensService, DataLensTournamentError

app = typer.Typer(no_args_is_help=True)


def _club_identity(name: str) -> ClubIdentity:
    aliases = {"единорог": "edinorog", "goldfish": "goldfish", "голдфиш": "goldfish"}
    normalized = aliases.get(name.strip().casefold(), name.strip().casefold())
    for identity in club_identities():
        if identity.name.casefold() == normalized:
            return identity
    available = ", ".join(identity.name for identity in club_identities())
    raise typer.BadParameter(f"Неизвестный клуб {name!r}; доступны: {available}")


@app.command("datalens")
def datalens_tournament(
    event_date: datetime = typer.Argument(..., formats=["%Y-%m-%d"], help="Дата турнира YYYY-MM-DD"),
    club: str = typer.Option(..., help="Название клуба в DataLens, например Единорог"),
) -> None:
    """Получить из DataLens турнир со всеми местами, игроками и колодами."""
    try:
        tournament = DataLensService().tournament(event_date.date(), club=club)
    except DataLensTournamentError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(1) from exc
    payload = {
        "date": tournament.date.isoformat(),
        "club": tournament.club,
        "format": tournament.format,
        "players": [player.model_dump() for player in tournament.players],
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("aetherhub")
def aetherhub_url(
    event_date: datetime = typer.Argument(..., formats=["%Y-%m-%d"], help="Дата турнира YYYY-MM-DD"),
    club: str = typer.Option(..., help="Клуб: Goldfish или Edinorog"),
    tournament_format: str = typer.Option("Pauper", "--format", help="Формат турнира"),
) -> None:
    """Найти только AetherHub URL турнира по клубу, дате и формату."""
    identity = _club_identity(club)
    if not identity.aetherhub_url:
        raise typer.BadParameter(f"Для клуба {identity.name} не настроена страница AetherHub")
    try:
        url = AetherhubService().find_tournament_url(identity.aetherhub_url, event_date.date(), tournament_format)
    except ValueError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(1) from exc
    if not url:
        typer.echo(
            f"Ошибка: турнир {identity.name} / {tournament_format} / {event_date.date().isoformat()} не найден",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo(url)
