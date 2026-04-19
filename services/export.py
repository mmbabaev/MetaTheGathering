from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Iterable, List, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from services.utils import get_tournament
from services.stats import StatsService


ExportFormat = Literal["csv", "markdown"]


class ExportService:
    def __init__(self, db: Session):
        self.db = db

    def _participants_query(self, tournament_id: int):
        return (
            select(
                models.Participant.id,
                models.User.username,
                models.User.tg_id,
                models.Archetype.name.label("archetype_name"),
                models.Participant.upvotes_count,
                models.Participant.downvotes_count,
                models.Participant.confirmed,
                models.Participant.added_by_admin,
                models.Participant.created_at,
            )
            .join(models.User, models.User.id == models.Participant.user_id)
            .join(
                models.Archetype,
                models.Archetype.id == models.Participant.archetype_id,
                isouter=True,
            )
            .where(models.Participant.tournament_id == tournament_id)
            .order_by(models.Participant.created_at.asc())
        )

    def export_participants_csv(
        self,
        tournament_id: int,
        file: io.TextIOBase | None = None,
        encoding: str = "utf-8",
    ) -> str:
        """
        Выгрузка участников турнира в CSV.
        Если file None — возвращает строку, иначе пишет в указанный файл и возвращает пустую строку.
        """
        get_tournament(self.db, tournament_id)  # ensure exists

        stmt = self._participants_query(tournament_id)
        rows = self.db.execute(stmt).all()

        headers = [
            "participant_id",
            "username",
            "tg_id",
            "archetype",
            "upvotes",
            "downvotes",
            "confirmed",
            "added_by_admin",
            "created_at",
        ]

        if file is not None:
            writer = csv.writer(file)
            writer.writerow(headers)
            for r in rows:
                writer.writerow(
                    [
                        r.id,
                        r.username or "",
                        r.tg_id,
                        r.archetype_name or "",
                        r.upvotes_count,
                        r.downvotes_count,
                        int(r.confirmed),
                        int(r.added_by_admin),
                        r.created_at.isoformat() if isinstance(r.created_at, datetime) else "",
                    ]
                )
            return ""

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)
        for r in rows:
            writer.writerow(
                [
                    r.id,
                    r.username or "",
                    r.tg_id,
                    r.archetype_name or "",
                    r.upvotes_count,
                    r.downvotes_count,
                    int(r.confirmed),
                    int(r.added_by_admin),
                    r.created_at.isoformat() if isinstance(r.created_at, datetime) else "",
                ]
            )
        return buf.getvalue()

    def export_meta_markdown(self, tournament_id: int) -> str:
        """
        Markdown‑таблица метагейма: архетип, количество игроков, суммарные голоса.
        Удобно кидать в Telegram / на сайт как текст.[web:61][web:67]
        """
        stats = StatsService(self.db)
        meta = stats.get_tournament_meta(tournament_id)

        if not meta:
            return "| Archetype | Players | Upvotes | Downvotes |\n|---|---|---|---|\n"

        lines: List[str] = []
        lines.append("| Archetype | Players | Upvotes | Downvotes |")
        lines.append("|---|---|---|---|")
        for row in meta:
            lines.append(
                f"| {row.archetype_name} | {row.count} | {row.upvotes_sum} | {row.downvotes_sum} |"
            )
        return "\n".join(lines)
