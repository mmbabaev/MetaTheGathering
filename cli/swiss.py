"""Debug CLI for the real internal Swiss engine (see ``services/debug_swiss.py``)."""

from __future__ import annotations

from typing import Optional

import typer
from sqlalchemy import select

from cli.db import get_db
from core import models
from core.config import app_cfg
from services.debug_swiss import (
    DEFAULT_PLAYERS,
    DEFAULT_PLAYOFF_SIZE,
    DEFAULT_SWISS_ROUNDS,
    DebugSwissService,
)
from services.endstep_table_titles import ENDSTEP_RU_CLUB
from services.internal_swiss import SwissStanding
from services.round_results import RoundResultError

app = typer.Typer(no_args_is_help=True, help="Отладка внутреннего Swiss-движка")


def _service(db) -> DebugSwissService:
    return DebugSwissService(db)


def _fail(exc: RoundResultError) -> None:
    typer.echo(f"✗ {exc}", err=True)
    raise typer.Exit(1)


def _resolve_tournament_id(db, tournament_id: Optional[int]) -> int:
    if tournament_id is not None:
        return tournament_id
    found = db.execute(
        select(models.Tournament)
        .where(models.Tournament.club == ENDSTEP_RU_CLUB)
        .order_by(models.Tournament.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if found is None:
        typer.echo("В debug-базе нет ни одного турнира Endstep. Создай его: swiss setup", err=True)
        raise typer.Exit(1)
    typer.echo(f"Турнир #{found.id}: {found.title} [{found.status.value}]")
    return found.id


def _admin_id(admin_id: Optional[int]) -> int:
    if admin_id is not None:
        return admin_id
    if app_cfg.owner_chat_id is None:
        typer.echo("Ошибка: в debug-конфиге не задан owner_chat_id. Передай --admin-id.", err=True)
        raise typer.Exit(1)
    return app_cfg.owner_chat_id


def _print_status(status) -> None:
    typer.echo(f"Турнир #{status.tournament_id}: {status.title}")
    typer.echo(f"  Статус:        {status.status}")
    typer.echo(f"  Игроков:       {status.active_players}")
    typer.echo(
        f"  Раундов:       {status.round_number}/{status.planned_rounds} "
        f"(Swiss {status.swiss_rounds} + плей-офф {status.playoff_size})"
    )
    typer.echo(f"  Большой формат: {'да' if status.large_format else 'нет'}")
    typer.echo(f"  Результаты собраны: {'да' if status.scores_collected else 'нет'}")
    typer.echo(f"  Можно играть дальше: {'да' if status.can_autoplay else 'нет'}")


def _print_standings(standings: list[SwissStanding], limit: int) -> None:
    typer.echo(f"{'#':>4}  {'Очки':>5}  {'Рекорд':>8}  {'OMW':>6}  {'GW':>6}  Имя")
    for row in standings[:limit]:
        typer.echo(
            f"{row.place:>4}  {row.match_points:>5}  {row.record:>8}  "
            f"{row.opponents_match_win_percentage:>6.1%}  {row.game_win_percentage:>6.1%}  "
            f"{row.display_name}{' ⛔' if row.dropped else ''}{f' · BYE ×{row.byes}' if row.byes else ''}"
        )


@app.command("setup")
def setup(
    players: int = typer.Option(DEFAULT_PLAYERS, "--players", "-p", help="Сколько фейковых игроков нужно"),
    rounds: int = typer.Option(DEFAULT_SWISS_ROUNDS, "--rounds", "-r", help="Число Swiss-раундов"),
    playoff: int = typer.Option(DEFAULT_PLAYOFF_SIZE, "--playoff", help="Размер плей-оффа: 8 или 16"),
    admin_id: Optional[int] = typer.Option(None, "--admin-id", help="tg_id администратора debug-базы"),
    fill: bool = typer.Option(True, "--fill/--no-fill", help="Сразу заполнить поле фейками"),
):
    """Создать debug-турнир Endstep на внутреннем Swiss и заполнить его игроками."""
    with get_db() as db:
        service = _service(db)
        try:
            tournament = service.create_tournament(
                players=players,
                rounds=rounds,
                playoff_size=playoff,
                admin_tg_id=_admin_id(admin_id),
            )
        except RoundResultError as exc:
            _fail(exc)
        typer.echo(f"✓ Создан турнир #{tournament.id}: {tournament.title}")
        planned = service.planned_rounds_for(tournament.swiss_rounds or 0, tournament.playoff_size or 0)
        typer.echo(
            f"  Swiss-раундов: {tournament.swiss_rounds}, плей-офф: {tournament.playoff_size} "
            f"(после наполнения поля — до {planned} раундов)"
        )
        if not fill:
            typer.echo("  Поле не заполнено (--no-fill). Заполни отдельно: swiss fill")
            return
        try:
            result = service.fill_players(tournament.id, players)
        except RoundResultError as exc:
            _fail(exc)
        typer.echo(f"✓ Добавлено игроков: {result.added}. Всего: {result.total}")
        typer.echo(f"  Дальше: python3 cli.py swiss step --id {tournament.id}")


@app.command("close-active")
def close_active():
    """Закрыть все активные турниры Endstep, чтобы освободить слот клуба."""
    with get_db() as db:
        service = _service(db)
        try:
            closed = service.close_active_debug_tournaments()
        except RoundResultError as exc:
            _fail(exc)
        if not closed:
            typer.echo("Активных турниров Endstep нет")
            return
        for tournament in closed:
            typer.echo(f"✓ Закрыт #{tournament.id}: {tournament.title}")


@app.command("fill")
def fill(
    tournament_id: Optional[int] = typer.Option(None, "--id", help="ID турнира (по умолчанию — последний Endstep)"),
    players: int = typer.Option(DEFAULT_PLAYERS, "--players", "-p", help="Сколько игроков должно быть в итоге"),
):
    """Добить фейковых игроков (с архетипом и деклистом) до нужного количества."""
    with get_db() as db:
        service = _service(db)
        target = _resolve_tournament_id(db, tournament_id)
        try:
            result = service.fill_players(target, players)
        except RoundResultError as exc:
            _fail(exc)
        typer.echo(f"✓ Добавлено: {result.added}. Всего игроков: {result.total}")


@app.command("step")
def step(
    tournament_id: Optional[int] = typer.Option(None, "--id", help="ID турнира (по умолчанию — последний Endstep)"),
    admin_id: Optional[int] = typer.Option(None, "--admin-id", help="tg_id администратора debug-базы"),
):
    """Случайно закрыть текущий раунд и создать следующий настоящим движком."""
    with get_db() as db:
        service = _service(db)
        target = _resolve_tournament_id(db, tournament_id)
        try:
            result = service.autoplay_round(target, _admin_id(admin_id))
        except RoundResultError as exc:
            _fail(exc)
        typer.echo(
            f"✓ Раунд {result.round_number}/{result.planned_rounds}: матчей {result.matches}"
            + (
                f" (дозаполнено результатов прошлого раунда: {result.completed_previous})"
                if result.completed_previous
                else ""
            )
        )


@app.command("run")
def run(
    tournament_id: Optional[int] = typer.Option(None, "--id", help="ID турнира (по умолчанию — последний Endstep)"),
    admin_id: Optional[int] = typer.Option(None, "--admin-id", help="tg_id администратора debug-базы"),
    finish: bool = typer.Option(False, "--finish", help="Сразу завершить турнир после последнего раунда"),
):
    """Сыграть все запланированные раунды подряд."""
    with get_db() as db:
        service = _service(db)
        target = _resolve_tournament_id(db, tournament_id)
        try:
            result = service.autoplay_all(target, _admin_id(admin_id))
        except RoundResultError as exc:
            _fail(exc)
        for step_result in result.rounds:
            typer.echo(
                f"  Раунд {step_result.round_number}/{step_result.planned_rounds}: "
                f"матчей {step_result.matches}, дополнено {step_result.completed_previous}"
            )
        typer.echo(f"✓ Сыграно раундов: {result.played}/{result.planned}")
        if not result.completed:
            typer.echo("⚠️ Не все раунды созданы — проверь status.", err=True)
            raise typer.Exit(1)
        if not finish:
            typer.echo(f"  Дальше: python3 cli.py swiss finish --id {target}")
            return
        try:
            standings = service.finish(target, _admin_id(admin_id))
        except RoundResultError as exc:
            _fail(exc)
        typer.echo("✓ Турнир завершён")
        _print_standings(standings, 20)


@app.command("finish")
def finish(
    tournament_id: Optional[int] = typer.Option(None, "--id", help="ID турнира (по умолчанию — последний Endstep)"),
    admin_id: Optional[int] = typer.Option(None, "--admin-id", help="tg_id администратора debug-базы"),
):
    """Завершить Swiss: расставить места и закрыть турнир."""
    with get_db() as db:
        service = _service(db)
        target = _resolve_tournament_id(db, tournament_id)
        try:
            standings = service.finish(target, _admin_id(admin_id))
        except RoundResultError as exc:
            _fail(exc)
        typer.echo("✓ Турнир завершён")
        _print_standings(standings, 20)


@app.command("status")
def status(
    tournament_id: Optional[int] = typer.Option(None, "--id", help="ID турнира (по умолчанию — последний Endstep)"),
):
    """Текущее состояние турнира: раунды, игроки, формат."""
    with get_db() as db:
        service = _service(db)
        target = _resolve_tournament_id(db, tournament_id)
        try:
            _print_status(service.status(target))
        except RoundResultError as exc:
            _fail(exc)


@app.command("standings")
def standings(
    tournament_id: Optional[int] = typer.Option(None, "--id", help="ID турнира (по умолчанию — последний Endstep)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Сколько строк показать"),
):
    """Показать стендинги по официальным тай-брейкам."""
    with get_db() as db:
        service = _service(db)
        target = _resolve_tournament_id(db, tournament_id)
        rows = service.standings(target)
        if not rows:
            typer.echo("Стендингов нет")
            return
        _print_standings(rows, limit)
