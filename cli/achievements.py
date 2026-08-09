"""CLI ачивок: пересчитать турнир, посмотреть полку игрока, вывести все выдачи.

Работает на той же debug-базе, что и остальной CLI, и не шлёт ничего в Telegram —
это инструмент проверки правил до публичного запуска.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from sqlalchemy import select

from cli.db import get_db
from core import models
from services.achievements import AchievementService, build_report
from services.achievements.history import AchievementHistory, counts_for_achievements, display_name
from services.season_stats import SeasonStatsService, SeasonStatsSnapshot
from services.user import UserService

app = typer.Typer(no_args_is_help=True)


def _record_text(record) -> str:
    winrate = "—" if record.winrate is None else f"{record.winrate:.2f}%"
    return f"{record.wins}-{record.losses}-{record.draws} ({winrate})"


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|")


def format_season_snapshot(snapshot: SeasonStatsSnapshot, *, player_limit: int = 30) -> str:
    """Compact Markdown for a human review; JSON remains the machine-readable contract."""
    quality = snapshot.quality
    lines = [
        f"# Срез сезонной статистики на {snapshot.as_of:%Y-%m-%d}",
        "",
        f"Клуб: {snapshot.club or 'все клубы'}.",
        (
            f"Качество данных: {quality.complete_tournaments}/{quality.tournaments_scanned} пригодных турниров; "
            f"{quality.scored_matches} матчей; {quality.unmatched_player_rows} несопоставленных строк парингов; "
            f"{quality.participants_without_pairing} регистраций без фактической игры."
        ),
        "",
        f"## Топ-{len(snapshot.popular_decks)} колод за {snapshot.deck_window_days} дней",
        "",
        "| # | Колода | Участия | Игроки | Участия зарегистрированных |",
        "|---:|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| {deck.rank} | {_markdown_cell(deck.deck)} | {deck.participations} | {deck.players} | "
        f"{deck.registered_participations} |"
        for deck in snapshot.popular_decks
    )
    lines.extend(
        [
            "",
            f"## Игроки (первые {min(player_limit, len(snapshot.players))} из {len(snapshot.players)})",
            "",
            "| Игрок | Матчи за историю | Худший H2H | Изменение винрейта | Достаточно матчей |",
            "|---|---|---|---:|:---:|",
        ]
    )
    for player in snapshot.players[:player_limit]:
        worst = player.worst_opponent
        worst_text = "—"
        if worst is not None:
            worst_text = f"{worst.opponent_name}: {worst.winrate:.2f}% ({worst.matches})"
        change = player.winrate_change
        delta = "—" if change.delta_percentage_points is None else f"{change.delta_percentage_points:+.2f} п.п."
        lines.append(
            f"| {_markdown_cell(player.name)} | {_record_text(player.record)} | "
            f"{_markdown_cell(worst_text)} | {delta} | {'да' if change.eligible else 'нет'} |"
        )
    return "\n".join(lines) + "\n"


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


@app.command("season-stats")
def season_stats(
    as_of: datetime = typer.Option(..., "--as-of", formats=["%Y-%m-%d"], help="Начало сезона YYYY-MM-DD"),
    club: Optional[str] = typer.Option(None, "--club", help="Только один клуб"),
    output_format: str = typer.Option("markdown", "--format", help="markdown или json"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Сохранить результат в файл"),
    history_days: int = typer.Option(365, "--history-days", min=1, help="Глубина head-to-head"),
    deck_window_days: int = typer.Option(120, "--deck-window-days", min=1, help="Окно популярности колод"),
    winrate_window_days: int = typer.Option(90, "--winrate-window-days", min=1, help="Размер каждого окна"),
    top_decks: int = typer.Option(10, "--top-decks", min=1, help="Сколько популярных колод оставить"),
    min_h2h_matches: int = typer.Option(3, "--min-h2h-matches", min=1, help="Минимум матчей с оппонентом"),
    min_window_matches: int = typer.Option(5, "--min-window-matches", min=1, help="Минимум матчей в каждом окне"),
    player_limit: int = typer.Option(30, "--player-limit", min=1, help="Игроков в Markdown; JSON содержит всех"),
):
    """Собрать read-only snapshot для проектирования сезонного бинго.

    Команда ничего не записывает в БД и ничего не отправляет в Telegram. Дата ``--as-of``
    является правой невключительной границей: для сезона 1 сентября учитываются данные
    не позднее 31 августа.
    """
    normalized_format = output_format.strip().casefold()
    if normalized_format not in {"markdown", "json"}:
        raise typer.BadParameter("--format должен быть markdown или json")

    with get_db() as db:
        snapshot = SeasonStatsService(db).build_snapshot(
            as_of=as_of,
            club=club,
            history_days=history_days,
            deck_window_days=deck_window_days,
            winrate_window_days=winrate_window_days,
            top_decks=top_decks,
            min_h2h_matches=min_h2h_matches,
            min_window_matches=min_window_matches,
        )

    rendered = (
        snapshot.model_dump_json(indent=2)
        if normalized_format == "json"
        else format_season_snapshot(snapshot, player_limit=player_limit)
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + ("\n" if normalized_format == "json" else ""), encoding="utf-8")
        typer.echo(str(output.resolve()))
        return
    typer.echo(rendered, nl=not rendered.endswith("\n"))


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
