"""Картинка «Итоговые стендинги»: список игроков с фоновой подсветкой по очкам.

Строка = место, имя, колода, очки. Фон строки красится по тиру очков (4-0, 3-0-1, 3-1,
остальные) — топовые результаты видно с одного взгляда.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Optional

from PIL import ImageDraw
from sqlalchemy.orm import Session

from core import models
from services.aetherhub_import_service import AetherhubImportService, StandingRow
from services.chart_style import (
    CREAM,
    FOOTER_GREY,
    GOLD,
    GREY,
    WIDTH,
    background,
    build_subtitle,
    draw_tracked,
    ellipsize,
    font,
)
from services.deck_book import strip_pictographs

MARGIN = 63
TITLE = "Итоговые стендинги"
SUBTITLE_Y = 130
FOOTER = "Победа 3 очка · ничья 1 · поражение 0"

TABLE_TOP = 210
ROW_H = 74
FOOTER_GAP = 40

# Колонки строки.
PLACE_X = MARGIN + 20  # номер места (правый край)
NAME_X = MARGIN + 60  # имя (левый край)
POINTS_X = WIDTH - MARGIN - 20  # очки (правый край)
DECK_X = WIDTH - MARGIN - 130  # колода (правый край, левее очков)
ROW_RADIUS = 12

# Тиры по очкам за матч (победа 3, ничья 1). Порог → цвет фона строки (тёмная тема).
# Приглушённые заливки, чтобы не спорить с кремовым текстом.
POINTS_UNDEFEATED = 12  # 4-0
POINTS_NO_LOSS_DRAW = 10  # 3-0-1 и подобные без поражений
POINTS_ONE_LOSS = 9  # 3-1

TIER_BG = {
    POINTS_UNDEFEATED: (0x2C, 0x40, 0x2E),  # зелёный — без поражений
    POINTS_NO_LOSS_DRAW: (0x3E, 0x3A, 0x22),  # золотисто-оливковый
    POINTS_ONE_LOSS: (0x40, 0x30, 0x1E),  # тёплый оранжевый
}
DECK_GREY = (0x8C, 0x8B, 0x86)


def tier_background(points: int) -> Optional[tuple]:
    """Цвет фона строки по очкам. None — обычный фон (не топ-тир)."""
    if points >= POINTS_UNDEFEATED:
        return TIER_BG[POINTS_UNDEFEATED]
    if points >= POINTS_NO_LOSS_DRAW:
        return TIER_BG[POINTS_NO_LOSS_DRAW]
    if points >= POINTS_ONE_LOSS:
        return TIER_BG[POINTS_ONE_LOSS]
    return None


@dataclass(frozen=True)
class StandingsData:
    """Данные для рисования стендингов — всё уже вынуто из БД."""

    rows: list[StandingRow]
    subtitle: str
    filename: str


def render_standings(rows: list[StandingRow], subtitle: str = "") -> bytes:
    """Собирает PNG со стендингами (без БД)."""
    height = TABLE_TOP + len(rows) * ROW_H + FOOTER_GAP + 40
    img = background(height)
    draw = ImageDraw.Draw(img)

    draw.text((WIDTH // 2, 18), TITLE, font=font("DejaVuSerif-Bold.ttf", 64), fill=CREAM, anchor="ma")
    if subtitle:
        draw_tracked(draw, subtitle, WIDTH // 2, SUBTITLE_Y, font("DejaVuSans.ttf", 30), GREY, 3)

    place_font = font("DejaVuSans.ttf", 30)
    name_font = font("DejaVuSans.ttf", 34)
    deck_font = font("DejaVuSans.ttf", 26)
    points_font = font("DejaVuSans-Bold.ttf", 34)

    for i, row in enumerate(rows):
        top = TABLE_TOP + i * ROW_H
        _draw_row(draw, row, top, place_font, name_font, deck_font, points_font)

    footer_y = TABLE_TOP + len(rows) * ROW_H + FOOTER_GAP
    draw.text((WIDTH // 2, footer_y), FOOTER, font=font("DejaVuSans.ttf", 24), fill=FOOTER_GREY, anchor="ma")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _draw_row(draw, row, top, place_font, name_font, deck_font, points_font) -> None:
    middle = top + ROW_H // 2
    bg = tier_background(row.points)
    if bg is not None:
        draw.rounded_rectangle((MARGIN, top + 4, WIDTH - MARGIN, top + ROW_H - 4), radius=ROW_RADIUS, fill=bg)

    draw.text((PLACE_X, middle), str(row.place), font=place_font, fill=GREY, anchor="rm")

    # Колода прижата к очкам; имя занимает всё, что осталось слева, с обрезкой по многоточию.
    # strip_pictographs: эмодзи в названии («🟢🔵🐸 Bogles») в DejaVu — квадраты-тофу.
    deck = strip_pictographs(row.archetype_name) if row.archetype_name else "—"
    deck = ellipsize(draw, deck, deck_font, 300)
    deck_left = draw.textlength(deck, font=deck_font)
    name_max = DECK_X - deck_left - NAME_X - 24
    name = ellipsize(draw, row.display_name, name_font, name_max)

    draw.text((NAME_X, middle), name, font=name_font, fill=CREAM, anchor="lm")
    draw.text((DECK_X, middle), deck, font=deck_font, fill=DECK_GREY, anchor="rm")
    draw.text((POINTS_X, middle), str(row.points), font=points_font, fill=GOLD, anchor="rm")


class StandingsImageService:
    def __init__(self, db: Session, imports: Optional[AetherhubImportService] = None):
        self.db = db
        self.imports = imports if imports is not None else AetherhubImportService(db)

    def prepare(self, tournament_id: int) -> Optional[StandingsData]:
        """Данные для стендингов одним походом в БД. None — стендингов ещё нет.

        Как и у графика: работа с БД остаётся в вызывающем потоке, а рисование можно унести
        в asyncio.to_thread (сессия SQLAlchemy между потоками не переносится).
        """
        rows = self.imports.get_standings(tournament_id)
        if not rows:
            return None
        tournament = self.db.get(models.Tournament, tournament_id)
        subtitle = build_subtitle(tournament.club, tournament.title, tournament.created_at) if tournament else ""
        return StandingsData(rows=rows, subtitle=subtitle, filename=f"standings_{tournament_id}.png")

    def render(self, tournament_id: int) -> Optional[tuple[bytes, str]]:
        """PNG со стендингами. None — стендингов ещё нет."""
        data = self.prepare(tournament_id)
        if data is None:
            return None
        return render_standings(data.rows, data.subtitle), data.filename
