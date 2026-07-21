"""Картинка «Метагейм-срез»: бублик с колодами турнира + легенда.

Сектор = архетип, размер сектора = число колод этого архетипа, цвет = цветовая
идентичность (см. services/deck_colors.py). В центре — общее число колод.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Optional, Sequence

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from core import models
from services.chart_style import (
    CREAM,
    CREAM_DIM,
    FOOTER_GREY,
    GOLD,
    GREY,
    SEPARATOR,
    WIDTH,
    background,
    build_subtitle,
    draw_tracked,
    ellipsize,
    font,
)
from services.deck_book import strip_pictographs
from services.deck_colors import DeckColorResolver, colors_for_deck_name, hex_for
from services.deck_mapping import general_archetype
from services.stats import StatsService

MARGIN = 63
COL_W = 488
COL_X = (MARGIN, 619)

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


@dataclass
class ChartSector:
    """Один архетип на графике."""

    name: str
    count: int
    color: str  # hex


@dataclass(frozen=True)
class ChartData:
    """Данные для рисования — всё уже вынуто из БД."""

    sectors: list[ChartSector]
    subtitle: str
    filename: str


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
    draw.text((cx, 477), str(total), font=font("DejaVuSerif-Bold.ttf", 132), fill=CREAM_DIM, anchor="mm")
    draw_tracked(draw, plural_decks(total).upper(), cx, 592, font("DejaVuSans.ttf", 26), GREY, 8)


def _draw_legend(draw: ImageDraw.ImageDraw, sectors: Sequence[ChartSector]) -> int:
    """Легенда в две колонки. Возвращает y нижней границы последней строки."""
    name_font = font("DejaVuSans.ttf", 34)
    count_font = font("DejaVuSans-Bold.ttf", 34)
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
    name = ellipsize(draw, strip_pictographs(sector.name), name_font, COL_W - NAME_DX - 60)
    draw.text((col_x + NAME_DX, middle), name, font=name_font, fill=CREAM, anchor="lm")
    draw.text((col_x + COL_W, middle), str(sector.count), font=count_font, fill=GOLD, anchor="rm")
    draw.line([(col_x - 14, top + ROW_H), (col_x + COL_W, top + ROW_H)], fill=SEPARATOR, width=1)


def render_sectors(sectors: Sequence[ChartSector], subtitle: str = "") -> bytes:
    """Собирает PNG из готовых секторов (без БД)."""
    rows_count = math.ceil(len(sectors) / 2)
    height = LEGEND_TOP + rows_count * ROW_H + FOOTER_GAP + 60
    img = background(height)
    draw = ImageDraw.Draw(img)

    draw.text((WIDTH // 2, 18), TITLE, font=font("DejaVuSerif-Bold.ttf", 78), fill=CREAM, anchor="ma")
    if subtitle:
        draw_tracked(draw, subtitle, WIDTH // 2, SUBTITLE_Y, font("DejaVuSans.ttf", 30), GREY, 3)
    _draw_donut(img, sectors)
    _draw_center_text(draw, sum(s.count for s in sectors))
    bottom = _draw_legend(draw, sectors)
    draw.text((WIDTH // 2, bottom + FOOTER_GAP), FOOTER, font=font("DejaVuSans.ttf", 26), fill=FOOTER_GREY, anchor="ma")

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
        """Секторы графика: колоды турнира сведены к ОБЩЕМУ типу, с цветом, по убыванию количества.

        Разные записи одной деки («Blue Delver»/«Blue Terror»; «Rakdos madness»/«BR madness»)
        схлопываются в один сектор по общему типу (services.deck_mapping / Archetype.general_name).
        Цвет сектора — по общему типу.
        """
        rows = self.stats.get_tournament_meta(tournament_id)
        if not rows:
            return []
        archetypes = self._archetypes_by_id([r.archetype_id for r in rows])

        groups: dict[str, ChartSector] = {}
        for row in rows:
            general = self._general_of(archetypes.get(row.archetype_id), row.archetype_name)
            sector = groups.get(general.lower())
            if sector is None:
                groups[general.lower()] = ChartSector(
                    name=general, count=row.count, color=hex_for(colors_for_deck_name(general))
                )
            else:
                sector.count += row.count
        return sorted(groups.values(), key=lambda s: -s.count)

    @staticmethod
    def _general_of(archetype: Optional[models.Archetype], archetype_name: str) -> str:
        """Общий тип колоды: из кэша Archetype.general_name, иначе считаем на лету по имени."""
        if archetype is not None and archetype.general_name:
            return archetype.general_name
        return general_archetype(archetype_name) or strip_pictographs(archetype_name)

    def prepare(self, tournament_id: int) -> Optional[ChartData]:
        """Всё, что нужно для рисования, одним походом в БД. None — колод ещё нет.

        Отделено от `render_sectors`, чтобы работу с БД можно было оставить в вызывающем
        потоке, а в `asyncio.to_thread` уносить только рисование: сессия SQLAlchemy не
        предназначена для переезда между потоками.
        """
        sectors = self.build_sectors(tournament_id)
        if not sectors:
            return None
        tournament = self.db.get(models.Tournament, tournament_id)
        subtitle = build_subtitle(tournament.club, tournament.title, tournament.created_at) if tournament else ""
        return ChartData(sectors=sectors, subtitle=subtitle, filename=f"meta_chart_{tournament_id}.png")

    def render(self, tournament_id: int) -> Optional[tuple[bytes, str]]:
        """PNG со срезом метагейма. None — в турнире ещё нет ни одной колоды."""
        data = self.prepare(tournament_id)
        if data is None:
            return None
        return render_sectors(data.sectors, data.subtitle), data.filename

    def _archetypes_by_id(self, ids: list[int]) -> dict[int, models.Archetype]:
        found = self.db.query(models.Archetype).filter(models.Archetype.id.in_(ids)).all()
        return {a.id: a for a in found}
