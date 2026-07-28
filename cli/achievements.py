"""CLI ачивок: пересчитать турнир, посмотреть полку игрока, вывести все выдачи.

Работает на той же debug-базе, что и остальной CLI, и не шлёт ничего в Telegram —
это инструмент проверки правил до публичного запуска.
"""

from __future__ import annotations

from typing import Optional

import typer
from sqlalchemy import select

from cli.db import get_db
from core import models
from services.achievements import AchievementService, build_report
from services.achievements.history import display_name
from services.user import UserService

app = typer.Typer(no_args_is_help=True)


@app.command("process")
def process(tournament_id: int = typer.Argument(..., help="ID турнира")):
    """Пересчитать ачивки турнира и показать отчёт (как он ушёл бы владельцу)."""
    with get_db() as db:
        result = AchievementService(db).process_tournament(tournament_id)
        if result is None:
            typer.echo("Турнир не найден или ещё не завершён (нет парингов / не у всех матчей счёт)")
            raise typer.Exit(1)
        messages = build_report(result)
        if not messages:
            typer.echo(f"#{tournament_id}: изменений нет (всё уже посчитано)")
            return
        for text in messages:
            typer.echo(text)
            typer.echo("")


@app.command("show")
def show(player: str = typer.Argument(..., help="Имя игрока, напр. «Иванов Иван»")):
    """Полка ачивок игрока: открытые и прогресс."""
    with get_db() as db:
        user = UserService(db).find_by_name(player)
        if user is None:
            typer.echo(f"Игрок «{player}» не найден")
            raise typer.Exit(1)
        views = AchievementService(db).list_for_user(user.id)
        typer.echo(f"{display_name(user)} — открыто {sum(1 for v in views if v.unlocked)} из {len(views)}")
        for view in views:
            definition = view.definition
            if view.unlocked:
                mark = "✅"
                tail = f" — {view.evidence}" if view.evidence else ""
            elif view.progress:
                mark = "▫️"
                tail = f" — {view.progress}/{definition.threshold or 0}"
            else:
                mark = "  "
                tail = ""
            typer.echo(f"{mark} {definition.title_with_level}{tail}")


@app.command("list")
def list_awards(
    limit: int = typer.Option(50, "--limit", "-n", help="Сколько последних выдач показать"),
    code: Optional[str] = typer.Option(None, "--code", help="Фильтр по коду ачивки"),
):
    """Последние выданные ачивки по всем игрокам."""
    with get_db() as db:
        stmt = select(models.UserAchievement).order_by(models.UserAchievement.awarded_at.desc()).limit(limit)
        if code:
            stmt = stmt.where(models.UserAchievement.code == code)
        rows = db.execute(stmt).scalars().all()
        if not rows:
            typer.echo("Выдач нет")
            return
        for row in rows:
            user = db.get(models.User, row.user_id)
            name = display_name(user) if user else f"user#{row.user_id}"
            typer.echo(
                f"{row.awarded_at:%Y-%m-%d %H:%M}  {name:24}  {row.code}:{row.level}"
                f"  турнир #{row.tournament_id}  {row.evidence or ''}"
            )
