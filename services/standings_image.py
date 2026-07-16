"""Картинка «Итоговые стендинги»: карточки игроков с пипами маны и подсветкой топов.

Строка = место, имя, пипы цветовой идентичности колоды, колода, очки. Топовые результаты
помечены цветным акцентом слева (по очкам). Длинные списки бьём на страницы по 30 игроков.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Optional

from PIL import ImageDraw
from sqlalchemy.orm import Session

from core import models
from services.aetherhub_import_service import AetherhubImportService, StandingRow
from services.chart_style import WIDTH, background, build_subtitle, ellipsize, font
from services.deck_book import strip_pictographs
from services.deck_colors import colors_for_deck_name

MARGIN = 63
TITLE = "Итоговые стендинги"
PAGE_SIZE = 30  # игроков на одну картинку

HEADER_Y = 40
TABLE_TOP = 150
ROW_H = 78
ROW_GAP = 8
FOOTER_GAP = 34

# Цвета текста — яркие и читаемые (по просьбе владельца).
INK = (0xF2, 0xF3, 0xF5)  # имя, место, очки
DECK_INK = (0xB9, 0xC0, 0xCB)  # колода — светло-серый, но читаемый
MUTED = (0x8A, 0x92, 0x9E)  # подзаголовок / пагинация
CARD_BG = (0x1B, 0x20, 0x2A)  # фон карточки строки
SEPARATOR = (0x2A, 0x30, 0x3B)  # тонкие вертикальные разделители колонок

# Акцент слева по очкам за матч (победа 3, ничья 1).
POINTS_UNDEFEATED = 12  # 4-0
POINTS_NO_LOSS_DRAW = 10  # 3-0-1 и подобные без поражений
POINTS_ONE_LOSS = 9  # 3-1
ACCENTS = {
    POINTS_UNDEFEATED: (0x54, 0xB8, 0x6A),  # зелёный — без поражений
    POINTS_NO_LOSS_DRAW: (0xE0, 0xB8, 0x4C),  # золотой
    POINTS_ONE_LOSS: (0xE0, 0x8A, 0x3C),  # оранжевый
}

# Цвета пипов маны — узнаваемые цвета MTG.
PIP_COLORS = {
    "W": (0xF3, 0xEE, 0xD6),
    "U": (0x3B, 0x7D, 0xD8),
    "B": (0x5A, 0x54, 0x66),
    "R": (0xD4, 0x45, 0x3C),
    "G": (0x3F, 0xA3, 0x5F),
}
PIP_D = 34  # диаметр пипа
PIP_GAP = 42  # шаг между пипами

# Геометрия колонок.
ACCENT_W = 6
PLACE_X = MARGIN + 46  # номер места (правый край)
NAME_X = MARGIN + 82  # имя (левый край)
PIPS_X = 560  # начало колонки пипов (левый край)
PIPS_COL_W = 200
DECK_X = PIPS_X + PIPS_COL_W  # колода (левый край)
POINTS_X = WIDTH - MARGIN - 30  # очки (правый край)
DECK_MAX = POINTS_X - 70 - DECK_X


def accent_color(points: int) -> Optional[tuple]:
    """Цвет левого акцента по очкам. None — не топ-тир."""
    if points >= POINTS_UNDEFEATED:
        return ACCENTS[POINTS_UNDEFEATED]
    if points >= POINTS_NO_LOSS_DRAW:
        return ACCENTS[POINTS_NO_LOSS_DRAW]
    if points >= POINTS_ONE_LOSS:
        return ACCENTS[POINTS_ONE_LOSS]
    return None


@dataclass(frozen=True)
class StandingsData:
    """Данные для рисования стендингов — всё уже вынуто из БД."""

    rows: list[StandingRow]
    subtitle: str
    filename_prefix: str


def render_standings_pages(rows: list[StandingRow], subtitle: str = "") -> list[bytes]:
    """PNG-страницы стендингов, по PAGE_SIZE игроков на страницу."""
    pages = [rows[i : i + PAGE_SIZE] for i in range(0, len(rows), PAGE_SIZE)]
    total = len(pages)
    return [_render_page(page, subtitle, i + 1, total) for i, page in enumerate(pages)]


def render_standings(rows: list[StandingRow], subtitle: str = "") -> bytes:
    """Одна картинка (первая страница) — для тестов и простых вызовов."""
    return render_standings_pages(rows, subtitle)[0]


def _render_page(rows: list[StandingRow], subtitle: str, page: int, total: int) -> bytes:
    height = TABLE_TOP + len(rows) * (ROW_H + ROW_GAP) + FOOTER_GAP + 30
    img = background(height)
    draw = ImageDraw.Draw(img)

    draw.text((MARGIN, HEADER_Y), TITLE, font=font("DejaVuSerif-Bold.ttf", 52), fill=INK, anchor="lm")
    if subtitle:
        draw.text((WIDTH - MARGIN, HEADER_Y), subtitle, font=font("DejaVuSans.ttf", 34), fill=MUTED, anchor="rm")

    name_font = font("DejaVuSans-Bold.ttf", 32)
    place_font = font("DejaVuSans-Bold.ttf", 30)
    deck_font = font("DejaVuSans.ttf", 28)
    points_font = font("DejaVuSans-Bold.ttf", 34)
    for i, row in enumerate(rows):
        top = TABLE_TOP + i * (ROW_H + ROW_GAP)
        _draw_row(draw, row, top, place_font, name_font, deck_font, points_font)

    if total > 1:
        footer_y = TABLE_TOP + len(rows) * (ROW_H + ROW_GAP) + FOOTER_GAP
        draw.text(
            (WIDTH - MARGIN, footer_y), f"{page} / {total}", font=font("DejaVuSans.ttf", 26), fill=MUTED, anchor="rm"
        )

    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _draw_row(draw, row, top, place_font, name_font, deck_font, points_font) -> None:
    middle = top + ROW_H // 2
    draw.rounded_rectangle((MARGIN, top, WIDTH - MARGIN, top + ROW_H), radius=14, fill=CARD_BG)

    accent = accent_color(row.points)
    if accent is not None:
        draw.rounded_rectangle((MARGIN, top + 6, MARGIN + ACCENT_W, top + ROW_H - 6), radius=3, fill=accent)

    # тонкие разделители колонок (пипы | колода | очки)
    for x in (PIPS_X - 20, DECK_X - 20, POINTS_X - 66):
        draw.line([(x, top + 16), (x, top + ROW_H - 16)], fill=SEPARATOR, width=1)

    draw.text((PLACE_X, middle), str(row.place), font=place_font, fill=INK, anchor="rm")

    name = ellipsize(draw, row.display_name, name_font, PIPS_X - 40 - NAME_X)
    draw.text((NAME_X, middle), name, font=name_font, fill=INK, anchor="lm")

    _draw_pips(draw, row.color_identity, PIPS_X, middle)

    deck = strip_pictographs(row.archetype_name) if row.archetype_name else "—"
    deck = ellipsize(draw, deck, deck_font, DECK_MAX)
    draw.text((DECK_X, middle), deck, font=deck_font, fill=DECK_INK, anchor="lm")

    draw.text((POINTS_X, middle), str(row.points), font=points_font, fill=INK, anchor="rm")


def _draw_pips(draw, color_identity: str, x_left: int, middle: int) -> None:
    """Ряд кружков цветовой идентичности колоды. Бесцветная/неизвестная — без пипов."""
    x = x_left
    for color in color_identity:
        fill = PIP_COLORS.get(color)
        if fill is None:
            continue
        top = middle - PIP_D // 2
        draw.ellipse((x, top, x + PIP_D, top + PIP_D), fill=fill, outline=(0, 0, 0), width=1)
        x += PIP_GAP


class StandingsImageService:
    def __init__(self, db: Session, imports: Optional[AetherhubImportService] = None):
        self.db = db
        self.imports = imports if imports is not None else AetherhubImportService(db)

    def prepare(self, tournament_id: int) -> Optional[StandingsData]:
        """Данные для стендингов одним походом в БД. None — стендингов ещё нет.

        Пипы (color_identity) резолвим по имени колоды здесь же — без похода в БД, так что
        рисование остаётся чистым CPU и уходит в поток (сессию SQLAlchemy туда не унести).
        """
        rows = self.imports.get_standings(tournament_id)
        if not rows:
            return None
        for row in rows:
            row.color_identity = colors_for_deck_name(row.archetype_name)
        tournament = self.db.get(models.Tournament, tournament_id)
        subtitle = build_subtitle(tournament.club, tournament.title, tournament.created_at) if tournament else ""
        return StandingsData(rows=rows, subtitle=subtitle, filename_prefix=f"standings_{tournament_id}")

    def render(self, tournament_id: int) -> Optional[list[tuple[bytes, str]]]:
        """Страницы стендингов [(png, filename)]. None — стендингов ещё нет."""
        data = self.prepare(tournament_id)
        if data is None:
            return None
        pages = render_standings_pages(data.rows, data.subtitle)
        return [(png, f"{data.filename_prefix}_{i + 1}.png") for i, png in enumerate(pages)]
