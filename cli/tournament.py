from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from sqlalchemy import select

from cli.db import get_db
from core import models
from core.config import app_cfg
from core.schemas import TournamentCreate
from services.aetherhub_import_service import AetherhubImportService
from services.aetherhub_service import AetherhubService
from services.export import ExportService
from services.tournament import TournamentService

app = typer.Typer(no_args_is_help=True)


def _default_chat_id() -> int:
    chat_id = app_cfg.edinorog_chat_id or app_cfg.goldfish_chat_id
    if not chat_id:
        typer.echo("Ошибка: chat_id не задан в debug конфиге", err=True)
        raise typer.Exit(1)
    return chat_id


@app.command("list")
def list_tournaments(
    all_chats: bool = typer.Option(False, "--all", help="Показать турниры всех чатов"),
    chat_id: Optional[int] = typer.Option(None, "--chat-id", help="Фильтр по chat_id"),
    limit: int = typer.Option(20, "--limit", "-n", help="Сколько турниров показать"),
):
    """Список последних турниров."""
    with get_db() as db:
        svc = TournamentService(db)
        if all_chats:
            stmt = select(models.Tournament).order_by(models.Tournament.created_at.desc()).limit(limit)
            tournaments = db.execute(stmt).scalars().all()
        else:
            cid = chat_id or _default_chat_id()
            tournaments = svc.list_tournaments_for_chat(cid, limit=limit)
        if not tournaments:
            typer.echo("Турниров нет")
            return
        for t in tournaments:
            typer.echo(
                f"#{t.id:3}  chat={t.chat_id}  [{t.status.value:12}]  {t.title}  ({t.created_at:%Y-%m-%d %H:%M})"
            )


@app.command("participants")
def list_participants(
    tournament_id: Optional[int] = typer.Option(None, "--id", help="ID турнира (по умолчанию — последний)"),
):
    """Список участников турнира с местом, архетипом и user_id."""
    with get_db() as db:
        svc = TournamentService(db)
        if tournament_id is None:
            tournaments = svc.list_tournaments_for_chat(_default_chat_id(), limit=1)
            if not tournaments:
                typer.echo("Турниров нет", err=True)
                raise typer.Exit(1)
            tournament_id = tournaments[0].id
            typer.echo(f"Турнир #{tournament_id}: {tournaments[0].title}")

        stmt = (
            select(models.Participant)
            .where(models.Participant.tournament_id == tournament_id)
            .order_by(models.Participant.final_place.asc().nulls_last(), models.Participant.id.asc())
        )
        participants = db.execute(stmt).scalars().all()

        if not participants:
            typer.echo("Участников нет")
            return

        typer.echo(f"{'#':>4}  {'user_id':>8}  {'Имя':30}  {'Архетип'}")
        typer.echo("-" * 70)
        for p in participants:
            place = str(p.final_place) if p.final_place is not None else "—"
            name = f"{p.user.first_name or ''} {p.user.last_name or ''}".strip() if p.user else "???"
            archetype = p.archetype.name if p.archetype else "—"
            typer.echo(f"{place:>4}  {p.user_id:>8}  {name:30}  {archetype}")


@app.command("create")
def create_tournament(title: str = typer.Argument(..., help="Название турнира")):
    """Создать новый турнир."""
    with get_db() as db:
        svc = TournamentService(db)
        t = svc.create_tournament(TournamentCreate(title=title, chat_id=_default_chat_id()))
        typer.echo(f"✓ Создан #{t.id}: {t.title}")


@app.command("delete-last")
def delete_last(yes: bool = typer.Option(False, "--yes", "-y", help="Не спрашивать подтверждения")):
    """Удалить последний турнир (по дате создания)."""
    with get_db() as db:
        svc = TournamentService(db)
        tournaments = svc.list_tournaments_for_chat(_default_chat_id(), limit=1)
        if not tournaments:
            typer.echo("Турниров нет")
            raise typer.Exit(1)
        t = tournaments[0]
        typer.echo(f"Турнир #{t.id}: {t.title}  [{t.status.value}]  создан {t.created_at:%Y-%m-%d %H:%M}")
        if not yes and not typer.confirm("Удалить?"):
            raise typer.Abort()
        svc.delete_tournament(t.id)
        typer.echo(f"✓ Удалён #{t.id}")


@app.command("import")
def import_aetherhub(
    url: str = typer.Argument(..., help="URL турнира на AetherHub"),
    tournament_id: Optional[int] = typer.Option(None, "--id", help="ID турнира (по умолчанию — активный)"),
):
    """Импортировать данные турнира с AetherHub."""
    with get_db() as db:
        svc = TournamentService(db)
        if tournament_id is None:
            active = svc.get_active_tournament_for_chat(_default_chat_id())
            if not active:
                typer.echo("Нет активного турнира. Укажи --id или создай турнир командой create.", err=True)
                raise typer.Exit(1)
            tournament_id = active.id
            typer.echo(f"Турнир #{tournament_id}: {active.title}")

        typer.echo(f"Загружаю {url}...")
        data = AetherhubService().fetch_tournament(url)
        typer.echo(f"Игроков: {len(data.players)}, раундов: {len(data.rounds)}")

        result = AetherhubImportService(db).import_tournament(tournament_id, data)
        svc.set_aetherhub_url(tournament_id, url)

        typer.echo("✓ Импорт завершён")
        typer.echo(f"  Зарегистрировано: {result.registered}")
        typer.echo(f"  Уже были:         {result.already_registered}")
        typer.echo(f"  Паринги:          {result.pairings_saved}")
        if result.created_names:
            names = ", ".join(result.created_names[:5])
            suffix = "…" if len(result.created_names) > 5 else ""
            typer.echo(f"  Новые игроки ({len(result.created_names)}): {names}{suffix}")


@app.command("export-excel")
def export_excel(
    tournament_id: Optional[int] = typer.Option(None, "--id", help="ID турнира (по умолчанию — последний)"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Путь для сохранения файла"),
):
    """Выгрузить участников турнира в Excel."""
    with get_db() as db:
        svc = TournamentService(db)
        if tournament_id is None:
            tournaments = svc.list_tournaments_for_chat(_default_chat_id(), limit=1)
            if not tournaments:
                typer.echo("Турниров нет", err=True)
                raise typer.Exit(1)
            tournament_id = tournaments[0].id
            typer.echo(f"Турнир #{tournament_id}: {tournaments[0].title}")

        data, filename = ExportService(db).export_participants_excel(tournament_id)
        out_path = (output or Path(filename)).resolve()
        out_path.write_bytes(data)
        typer.echo(f"✓ Сохранено: {out_path}  ({len(data):,} байт)")
