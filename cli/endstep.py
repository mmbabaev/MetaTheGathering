from __future__ import annotations

import typer

from core.config import settings
from services.endstep import EndstepApiError, EndstepClient

app = typer.Typer(no_args_is_help=True)


@app.command("find")
def find_players(
    usernames: list[str] = typer.Argument(..., help="Один или несколько точных ников Endstep"),
    format_name: str = typer.Option("Pauper", "--format", help="Ranked-формат Endstep"),
    season_id: str | None = typer.Option(None, "--season", help="ID сезона; по умолчанию текущий"),
) -> None:
    """Найти игроков в ranked-лидерборде Endstep без записи в БД."""

    client = EndstepClient(settings.ENDSTEP_API_URL)
    try:
        lookups = client.find_players(usernames, format_name=format_name, season_id=season_id)
    except EndstepApiError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(1) from exc

    for lookup in lookups:
        player = lookup.player
        if len(lookup.exact_matches) > 1:
            typer.echo(f"? {lookup.requested_username}: найдено несколько аккаунтов с таким ником")
            continue
        if player is None:
            typer.echo(f"— {lookup.requested_username}: не найден")
            continue
        place = f"#{player.rank}" if player.rank is not None else "без места"
        status = " · provisional" if player.provisional else ""
        typer.echo(
            f"{place} {player.username} — {player.rating} ±{player.rd} · "
            f"{player.wins}–{player.losses}–{player.draws}{status}"
        )
