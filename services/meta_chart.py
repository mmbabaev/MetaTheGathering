"""Картинка «Метагейм-срез»: бублик с колодами турнира + легенда.

Сектор = архетип, размер сектора = число колод этого архетипа, цвет = цветовая
идентичность (см. services/deck_colors.py). В центре — общее число колод.
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from core import models
from services.deck_colors import DeckColorResolver, hex_for
from services.stats import StatsService

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

WIDTH = 1179
MARGIN = 63
COL_W = 488
COL_X = (MARGIN, 619)

BG_TOP = (0x16, 0x17, 0x1C)
BG_BOTTOM = (0x0D, 0x0E, 0x13)
CREAM = (0xFC, 0xFB, 0xF6)
CREAM_DIM = (0xF3, 0xEF, 0xE4)
GREY = (0x9F, 0x9E, 0x99)
GOLD = (0xC4, 0xA6, 0x6A)
SEPARATOR = (0x21, 0x22, 0x27)
FOOTER_GREY = (0x4E, 0x50, 0x58)

DONUT_CENTER = (589, 517)
R_OUTER = 325
R_INNER = 208
SECTOR_GAP_DEG = 1.6
# Зазор не может съесть больше этой доли сектора — иначе узкие секторы исчезают.
MAX_GAP_SHARE = 0.5
SUPERSAMPLE = 3

SUBTITLE_Y = 130

LEGEND_TOP = 940
ROW_H = 96
SWATCH = 24
SWATCH_RADIUS = 6
NAME_DX = 56
FOOTER_GAP = 46

TITLE = "Метагейм-срез"
FOOTER = "Цвет сектора — цветовая идентичность колоды"

# Клуб в подзаголовке — текстом: эмодзи (🦄/🐠) в DejaVu нет, вышли бы квадраты-тофу.
CLUB_NAMES = {"edinorog": "Единорог", "goldfish": "Goldfish"}

# Дату берём из названия турнира («Pauper 13.07.2026») — это дата самого турнира,
# а created_at может отличаться (турнир заводят заранее или задним числом).
_DATE_IN_TITLE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")


@dataclass
class ChartSector:
    """Один архетип на графике."""

    name: str
    count: int
    color: str  # hex


# Эмодзи и прочие пиктограммы: в DejaVu для них нет глифов — без чистки легенда
# заполнится квадратами-тофу. Игроки часто пишут «🟢🔵🐸 Bogles»; сам цвет при этом
# уже учтён в services/deck_colors.py и продублирован квадратиком в легенде.
_PICTOGRAPHS_RE = re.compile(
    "["
    "\U0001f000-\U0001faff"  # эмодзи, цветные квадраты и круги
    "←-⇿"  # стрелки
    "⌀-⏿"  # технические символы
    "☀-➿"  # прочие символы и дингбаты (⚫ ⚪ ⚙)
    "⬀-⯿"
    "️"  # variation selector — «хвост» цветных эмодзи
    "‍"  # zero-width joiner
    "]"
)


def _font(filename: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_FONT_DIR / filename), size)


def display_name(name: str) -> str:
    """Название колоды для легенды: без эмодзи и лишних пробелов."""
    cleaned = re.sub(r"\s+", " ", _PICTOGRAPHS_RE.sub("", name)).strip()
    return cleaned or name.strip()


def build_subtitle(club: Optional[str], title: str, fallback_date: Optional[datetime] = None) -> str:
    """Подзаголовок графика: «Единорог · 13.07.2026». Пустая строка — если нечего показать."""
    match = _DATE_IN_TITLE_RE.search(title or "")
    date = match.group(1) if match else (fallback_date.strftime("%d.%m.%Y") if fallback_date else None)
    club_name = CLUB_NAMES.get((club or "").strip().lower()) or (club or "").strip() or None
    return " · ".join(part for part in (club_name, date) if part)


def plural_decks(n: int) -> str:
    """«1 колода», «3 колоды», «5 колод» — подпись под числом в центре."""
    if 11 <= n % 100 <= 14:
        return "колод"
    last = n % 10
    if last == 1:
        return "колода"
    if 2 <= last <= 4:
        return "колоды"
    return "колод"


def _background(height: int) -> Image.Image:
    """Фон с вертикальным градиентом, как в макете."""
    img = Image.new("RGB", (WIDTH, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(height - 1, 1)
        color = tuple(round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)
    return img


def _draw_donut(img: Image.Image, sectors: Sequence[ChartSector]) -> None:
    """Бублик с сглаживанием: рисуем в увеличенном масштабе и уменьшаем обратно."""
    total = sum(s.count for s in sectors)
    if total <= 0:
        return

    size = R_OUTER * 2 * SUPERSAMPLE
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    outer_box = (0, 0, size - 1, size - 1)
    pad = (R_OUTER - R_INNER) * SUPERSAMPLE
    inner_box = (pad, pad, size - 1 - pad, size - 1 - pad)

    angle = -90.0
    for sector in sectors:
        span = 360.0 * sector.count / total
        # Зазор сужаем под узкий сектор: фиксированные 1.6° съедали сектор целиком,
        # если его доля меньше зазора (одиночная колода на турнире 225+), — в легенде
        # строка есть, а в бублике дыра.
        gap = min(SECTOR_GAP_DEG, span * MAX_GAP_SHARE)
        draw.pieslice(outer_box, angle + gap / 2, angle + span - gap / 2, fill=sector.color)
        angle += span

    # Дырка: прозрачность вместо цвета фона — иначе на градиенте будет видно пятно.
    draw.ellipse(inner_box, fill=(0, 0, 0, 0))

    donut = layer.resize((R_OUTER * 2, R_OUTER * 2), Image.LANCZOS)
    img.paste(donut, (DONUT_CENTER[0] - R_OUTER, DONUT_CENTER[1] - R_OUTER), donut)


def _draw_center_text(draw: ImageDraw.ImageDraw, total: int) -> None:
    cx = DONUT_CENTER[0]
    draw.text((cx, 477), str(total), font=_font("DejaVuSerif-Bold.ttf", 132), fill=CREAM_DIM, anchor="mm")
    _draw_tracked(draw, plural_decks(total).upper(), cx, 592, _font("DejaVuSans.ttf", 26), GREY, 8)


def _draw_tracked(
    draw: ImageDraw.ImageDraw,
    text: str,
    cx: int,
    cy: int,
    font: ImageFont.FreeTypeFont,
    fill: tuple,
    tracking: int,
) -> None:
    """Текст с разрядкой, центрированный по (cx, cy)."""
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, cy), ch, font=font, fill=fill, anchor="lm")
        x += w + tracking


def _draw_legend(draw: ImageDraw.ImageDraw, sectors: Sequence[ChartSector]) -> int:
    """Легенда в две колонки. Возвращает y нижней границы последней строки."""
    name_font = _font("DejaVuSans.ttf", 34)
    count_font = _font("DejaVuSans-Bold.ttf", 34)
    bottom = LEGEND_TOP
    for i, sector in enumerate(sectors):
        col_x = COL_X[i % 2]
        top = LEGEND_TOP + (i // 2) * ROW_H
        _draw_legend_row(draw, sector, col_x, top, name_font, count_font)
        bottom = top + ROW_H
    return bottom


def _draw_legend_row(
    draw: ImageDraw.ImageDraw,
    sector: ChartSector,
    col_x: int,
    top: int,
    name_font: ImageFont.FreeTypeFont,
    count_font: ImageFont.FreeTypeFont,
) -> None:
    middle = top + ROW_H // 2
    draw.rounded_rectangle(
        (col_x, middle - SWATCH // 2, col_x + SWATCH, middle + SWATCH // 2),
        radius=SWATCH_RADIUS,
        fill=sector.color,
    )
    name = _ellipsize(draw, display_name(sector.name), name_font, COL_W - NAME_DX - 60)
    draw.text((col_x + NAME_DX, middle), name, font=name_font, fill=CREAM, anchor="lm")
    draw.text((col_x + COL_W, middle), str(sector.count), font=count_font, fill=GOLD, anchor="rm")
    draw.line([(col_x - 14, top + ROW_H), (col_x + COL_W, top + ROW_H)], fill=SEPARATOR, width=1)


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    """Обрезает длинное название колоды многоточием, чтобы не наехать на счётчик."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


def render_sectors(sectors: Sequence[ChartSector], subtitle: str = "") -> bytes:
    """Собирает PNG из готовых секторов (без БД)."""
    rows_count = math.ceil(len(sectors) / 2)
    height = LEGEND_TOP + rows_count * ROW_H + FOOTER_GAP + 60
    img = _background(height)
    draw = ImageDraw.Draw(img)

    draw.text((WIDTH // 2, 18), TITLE, font=_font("DejaVuSerif-Bold.ttf", 78), fill=CREAM, anchor="ma")
    if subtitle:
        _draw_tracked(draw, subtitle, WIDTH // 2, SUBTITLE_Y, _font("DejaVuSans.ttf", 30), GREY, 3)
    _draw_donut(img, sectors)
    _draw_center_text(draw, sum(s.count for s in sectors))
    bottom = _draw_legend(draw, sectors)
    draw.text(
        (WIDTH // 2, bottom + FOOTER_GAP), FOOTER, font=_font("DejaVuSans.ttf", 26), fill=FOOTER_GREY, anchor="ma"
    )

    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


class MetaChartService:
    def __init__(
        self,
        db: Session,
        stats: Optional[StatsService] = None,
        colors: Optional[DeckColorResolver] = None,
    ):
        self.db = db
        self.stats = stats if stats is not None else StatsService(db)
        self.colors = colors if colors is not None else DeckColorResolver(db)

    def build_sectors(self, tournament_id: int) -> list[ChartSector]:
        """Секторы графика: архетипы турнира с цветом, по убыванию количества колод."""
        rows = self.stats.get_tournament_meta(tournament_id)
        if not rows:
            return []
        archetypes = self._archetypes_by_id([r.archetype_id for r in rows])
        identities = self.colors.resolve_many(archetypes.values())
        return [
            ChartSector(
                name=row.archetype_name,
                count=row.count,
                color=hex_for(identities.get(row.archetype_id)),
            )
            for row in rows
        ]

    def render(self, tournament_id: int) -> Optional[tuple[bytes, str]]:
        """PNG со срезом метагейма. None — в турнире ещё нет ни одной колоды."""
        sectors = self.build_sectors(tournament_id)
        if not sectors:
            return None
        tournament = self.db.get(models.Tournament, tournament_id)
        subtitle = build_subtitle(tournament.club, tournament.title, tournament.created_at) if tournament else ""
        return render_sectors(sectors, subtitle), f"meta_chart_{tournament_id}.png"

    def _archetypes_by_id(self, ids: list[int]) -> dict[int, models.Archetype]:
        found = self.db.query(models.Archetype).filter(models.Archetype.id.in_(ids)).all()
        return {a.id: a for a in found}
