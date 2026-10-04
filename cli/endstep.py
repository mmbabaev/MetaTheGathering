from __future__ import annotations

import typer

from core.config import settings
from core.database import SessionLocal
from services.endstep import EndstepApiError, EndstepClient
from services.endstep_tournament_import import EndstepImportError, EndstepTournamentImporter
from services.scryfall_cards import ScryfallCardResolver, ScryfallResolveError

app = typer.Typer(no_args_is_help=True)
import_app = typer.Typer(no_args_is_help=True)


@import_app.command("import-tournament")
def import_tournament(
    external_key: str = typer.Option(..., "--key", help="Стабильный ID/URL турнира в Endstep"),
    slug: str = typer.Option(..., "--slug", help="Публичный slug результата"),
    title: str = typer.Option(..., "--title", help="Название турнира"),
    standings: str = typer.Option(..., "--standings", help="CSV standings"),
    pairings: str = typer.Option(..., "--pairings", help="CSV pairings"),
    decklists: str = typer.Option(..., "--decklists", help="CSV decklists"),
    format_name: str = typer.Option("Pauper", "--format", help="Формат турнира"),
    resolve_cards: bool = typer.Option(
        False,
        "--resolve-cards/--no-resolve-cards",
        help="Сопоставить названия карт с кэшем Scryfall после импорта",
    ),
) -> None:
    """Импортировать три CSV Endstep в локальный read-only snapshot."""

    db = SessionLocal()
    try:
        summary = EndstepTournamentImporter(db).import_csvs(
            external_key=external_key,
            slug=slug,
            title=title,
            standings_path=standings,
            pairings_path=pairings,
            decklists_path=decklists,
            format_name=format_name,
        )
        if resolve_cards:
            resolved = ScryfallCardResolver(db).resolve_tournament(summary.tournament_id)
        else:
            resolved = 0
    except (EndstepImportError, ScryfallResolveError) as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(1) from exc
    finally:
        db.close()

    typer.echo(
        f"Импортирован турнир #{summary.tournament_id}: standings={summary.standings}, "
        f"pairings={summary.pairings}, cards={summary.deck_cards}, "
        f"matched_users={summary.matched_users}, scryfall_cards={resolved}"
    )


@import_app.command("resolve-tournament-cards")
def resolve_tournament_cards(
    tournament_id: int = typer.Argument(..., help="ID локального Endstep snapshot"),
    force: bool = typer.Option(False, "--force", help="Повторить уже завершённые lookup’ы"),
) -> None:
    """Дозаполнить Scryfall metadata для уже импортированной колоды."""

    db = SessionLocal()
    try:
        resolved = ScryfallCardResolver(db).resolve_tournament(tournament_id, force=force)
    except ScryfallResolveError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(1) from exc
    finally:
        db.close()
    typer.echo(f"Scryfall: resolved={resolved}")


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
