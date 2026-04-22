from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import List, Literal

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.messages import format_participant_name
from core import models
from services.stats import StatsService
from services.utils import get_tournament

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

    def export_participants_excel(self, tournament_id: int) -> tuple[bytes, str]:
        """Возвращает (bytes, filename) для Excel-файла списка участников."""
        t = get_tournament(self.db, tournament_id)
        participants = self.db.query(models.Participant).filter_by(tournament_id=tournament_id).all()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Участники"

        header_fill = PatternFill(start_color="2E7D32", end_color="2E7D32", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        for col, h in enumerate(["@Ник", "Имя Фамилия", "Колода"], 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

        for row, p in enumerate(participants, 2):
            username = f"@{p.user.username}" if p.user and p.user.username else ""
            full_name = format_participant_name(
                p.user.first_name if p.user else None,
                p.user.last_name if p.user else None,
            )
            deck = p.archetype.name if p.archetype else ""
            ws.cell(row=row, column=1, value=username)
            ws.cell(row=row, column=2, value=full_name)
            ws.cell(row=row, column=3, value=deck)

        ws.column_dimensions["A"].width = 22
        ws.column_dimensions["B"].width = 28
        ws.column_dimensions["C"].width = 30

        buf = io.BytesIO()
        wb.save(buf)
        filename = f"{t.title.replace(' ', '_')}.xlsx"
        return buf.getvalue(), filename

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
            lines.append(f"| {row.archetype_name} | {row.count} | {row.upvotes_sum} | {row.downvotes_sum} |")
        return "\n".join(lines)
