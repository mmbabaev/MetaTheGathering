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
from services.achievements.history import AchievementHistory, counts_for_achievements, display_name
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


@app.command("audit")
def audit():
    """Показать, сколько истории вообще годится для ачивок.

    Ачивка требует трёх вещей разом: паринги со счётом, записанную колоду и отметку «кто
    записал» (гейт §2.5). Если отметки нет — турнир в зачёт не идёт, и бэкафилл по нему
    промолчит. Команда отвечает на вопрос «почему выдач так мало», не запуская сам бэкафилл.
    """
    with get_db() as db:
        history = AchievementHistory(db)
        tournaments = db.execute(select(models.Tournament)).scalars().all()
        complete = [t for t in tournaments if history.is_complete(t.id)]

        participants = db.execute(select(models.Participant, models.User).join(models.User)).all()
        with_deck = [p for p, _ in participants if p.archetype_id is not None]
        eligible = [p for p, u in participants if counts_for_achievements(p, u) and u.tg_id > 0]

        typer.echo(f"Турниров: {len(tournaments)}, со счётом у всех матчей: {len(complete)}")
        typer.echo(f"Участий: {len(participants)}, с колодой: {len(with_deck)}, в зачёт ачивок: {len(eligible)}")

        if not complete:
            typer.echo("\n⚠️  Ни один турнир не считается завершённым — нет парингов со счётом.")
        if with_deck and not eligible:
            typer.echo(
                "\n⚠️  Колоды есть, но ни у одного участия не заполнено deck_added_by_tg_id "
                "(«кто записал»). По таким турнирам ачивки не выдаются — это ожидаемо для\n"
                "    старых данных, записанных до появления поля."
            )


@app.command("backfill")
def backfill(
    club: Optional[str] = typer.Option(None, "--club", help="Только турниры этого клуба"),
    apply: bool = typer.Option(False, "--apply", help="Записать выдачи (без флага — только показать)"),
    top: int = typer.Option(20, "--top", help="Сколько игроков показать в сводке"),
):
    """Прогнать движок по всей истории турниров.

    Без ``--apply`` ничего не пишет — показывает, что выдалось бы. С ``--apply`` выдачи
    помечаются как уже уведомлённые: за прошлые турниры писать игрокам нечего.
    """
    with get_db() as db:
        report = AchievementService(db).backfill(club=club, dry_run=not apply)

        mode = "ПРИМЕНЕНО" if apply else "черновой прогон (ничего не записано)"
        typer.echo(f"{mode}: турниров обсчитано {report.tournaments}, пропущено {report.skipped}")
        typer.echo(f"Выдач: {len(report.granted)}")

        if report.by_code:
            typer.echo("\nПо ачивкам:")
            for code, count in sorted(report.by_code.items(), key=lambda kv: -kv[1]):
                typer.echo(f"  {code:12} {count}")

        if report.by_player:
            typer.echo(f"\nТоп игроков (до {top}):")
            for player, count in sorted(report.by_player.items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
                typer.echo(f"  {player:28} {count}")

        if not apply and report.granted:
            typer.echo("\nЧтобы записать: python3 cli.py achievements backfill --apply")


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


@app.command("events")
def list_progress_events(
    limit: int = typer.Option(50, "--limit", "-n", help="Сколько последних events показать"),
    user_id: Optional[int] = typer.Option(None, "--user-id"),
    code: Optional[str] = typer.Option(None, "--code"),
):
    """Immutable progress audit log with before/after and source versions."""
    with get_db() as db:
        stmt = select(models.AchievementProgressEvent).order_by(models.AchievementProgressEvent.id.desc()).limit(limit)
        if user_id is not None:
            stmt = stmt.where(models.AchievementProgressEvent.user_id == user_id)
        if code:
            stmt = stmt.where(models.AchievementProgressEvent.code == code)
        for event in db.execute(stmt).scalars().all():
            typer.echo(
                f"#{event.id} {event.event_type} user#{event.user_id} {event.code}: "
                f"{event.before_value} -> {event.after_value} tournament#{event.tournament_id} "
                f"ruleset={event.ruleset_version} stats={event.stats_version}"
            )


@app.command("replay-event")
def replay_event(
    event_id: int = typer.Argument(...),
    apply: bool = typer.Option(False, "--apply", help="Применить переход; без флага только dry-run"),
):
    """Dry-run/replay one progress cell; conflicting newer state is never overwritten."""
    with get_db() as db:
        result = AchievementService(db).replay_progress_event(event_id, apply=apply)
        mode = "applied" if apply else "dry-run"
        typer.echo(
            f"{mode}: event#{result.event_id}, current={result.current_value}, target={result.target_value}, "
            f"changed={result.changed}, conflict={result.conflict}"
        )
        if result.conflict:
            raise typer.Exit(2)


@app.command("override-progress")
def override_progress(
    user_id: int = typer.Argument(...),
    code: str = typer.Argument(...),
    value: int = typer.Argument(...),
    reason: str = typer.Option(..., "--reason", help="Обязательная причина owner override"),
    tournament_id: Optional[int] = typer.Option(None, "--tournament-id"),
):
    """Owner override recorded as a separate immutable event."""
    with get_db() as db:
        event = AchievementService(db).override_progress(
            user_id,
            code,
            value,
            reason,
            tournament_id=tournament_id,
        )
        typer.echo(f"override event #{event.id}: {event.before_value} -> {event.after_value}")
