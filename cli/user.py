from __future__ import annotations

from typing import Optional

import typer
from sqlalchemy import select

from cli.db import get_db
from core import models
from services.user import UserService

app = typer.Typer(no_args_is_help=True)


def _fmt_user(u: models.User) -> str:
    name = f"{u.first_name or ''} {u.last_name or ''}".strip() or "—"
    username = f"@{u.username}" if u.username else "—"
    return f"id={u.id}  tg_id={u.tg_id}  {username}  {name}"


@app.command("show")
def show_user(
    user_id: Optional[int] = typer.Option(None, "--id", help="Внутренний user_id"),
    tg_id: Optional[int] = typer.Option(None, "--tg-id", help="Telegram user_id"),
    username: Optional[str] = typer.Option(None, "--username", help="Telegram username (без @)"),
):
    """Показать информацию о пользователе."""
    with get_db() as db:
        svc = UserService(db)
        user = None
        if user_id is not None:
            user = svc.get_by_id(user_id)
        elif tg_id is not None:
            user = svc.get_by_tg_id(tg_id)
        elif username is not None:
            user = svc.get_by_username(username)
        else:
            typer.echo("Укажи --id, --tg-id или --username", err=True)
            raise typer.Exit(1)

        if not user:
            typer.echo("Пользователь не найден", err=True)
            raise typer.Exit(1)

        typer.echo(_fmt_user(user))

        stmt = select(models.Participant).where(models.Participant.user_id == user.id)
        participants = db.execute(stmt).scalars().all()
        if participants:
            typer.echo(f"  Участие в турнирах ({len(participants)}):")
            for p in participants:
                place = str(p.final_place) if p.final_place is not None else "—"
                typer.echo(f"    tournament_id={p.tournament_id}  place={place}")


@app.command("merge")
def merge_users(
    source_id: int = typer.Option(..., "--from", help="ID пользователя-источника (будет удалён)"),
    target_id: int = typer.Option(..., "--into", help="ID пользователя-цели (останется)"),
    adopt_name: bool = typer.Option(True, "--adopt-name/--keep-name", help="Скопировать имя источника в цель"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Не спрашивать подтверждения"),
):
    """Слить двух пользователей: перенести участие и историю от --from к --into, удалить --from."""
    with get_db() as db:
        svc = UserService(db)
        source = svc.get_by_id(source_id)
        target = svc.get_by_id(target_id)

        if not source:
            typer.echo(f"Источник id={source_id} не найден", err=True)
            raise typer.Exit(1)
        if not target:
            typer.echo(f"Цель id={target_id} не найден", err=True)
            raise typer.Exit(1)

        typer.echo(f"Источник:  {_fmt_user(source)}")
        typer.echo(f"Цель:      {_fmt_user(target)}")
        if adopt_name:
            typer.echo(f"Имя цели будет изменено на: {source.first_name or ''} {source.last_name or ''}".strip())

        if not yes and not typer.confirm("Слить?"):
            raise typer.Abort()

        ok = svc.merge_users_by_id(source_id, target_id, adopt_name=adopt_name)
        if ok:
            typer.echo(f"✓ Слито: id={source_id} → id={target_id}")
        else:
            typer.echo("Слияние не выполнено", err=True)
            raise typer.Exit(1)
