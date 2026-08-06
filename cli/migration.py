from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import typer

from core.clubs import ClubIdentity, club_identities
from core.config import settings
from services.aetherhub_service import AetherhubService
from services.datalens import DataLensService, DataLensTournamentError
from services.magicoculus import MagicOculusClient
from services.tournament_migration import HistoricalTournamentMigrator, TournamentMigrationReport

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


def _write_report(path: Path, report: TournamentMigrationReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


@app.command("all")
def migrate_all(
    club: list[str] = typer.Option([], "--club", help="Ограничить клубами; по умолчанию Рыба и Единорог"),
    from_date: datetime | None = typer.Option(None, "--from-date", formats=["%Y-%m-%d"]),
    to_date: datetime | None = typer.Option(None, "--to-date", formats=["%Y-%m-%d"]),
    report_path: Path = typer.Option(..., "--report", help="JSON checkpoint и итоговый отчёт"),
    execute: bool = typer.Option(False, "--execute", help="Выполнить реальные POST в Magic Oculus"),
) -> None:
    """Проверить или загрузить все доступные DataLens-дейлики."""
    dates = None
    if from_date or to_date:
        batch = DataLensService().all_tournaments()
        lower = from_date.date() if from_date else min(row.date for row in batch.tournaments)
        upper = to_date.date() if to_date else max(row.date for row in batch.tournaments)
        dates = {lower + timedelta(days=offset) for offset in range((upper - lower).days + 1)}
        datalens = CachedDataLensService(batch)
    else:
        datalens = DataLensService()
    migrator = HistoricalTournamentMigrator(
        datalens,
        AetherhubService(),
        MagicOculusClient(settings.MAGIC_OCULUS_API_URL),
    )
    report = migrator.run(
        execute=execute,
        clubs=set(club) or None,
        dates=dates,
        on_update=lambda current: _write_report(report_path, current),
    )
    typer.echo(json.dumps(report.counts(), ensure_ascii=False, sort_keys=True))
    typer.echo(str(report_path))


class CachedDataLensService:
    """Reuse an already downloaded batch when CLI date bounds are applied."""

    def __init__(self, batch) -> None:
        self._batch = batch

    def all_tournaments(self):
        return self._batch
