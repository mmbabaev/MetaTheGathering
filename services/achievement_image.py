"""Картинки ачивок: карточка одной ачивки и «полка» игрока.

Тот же визуальный язык, что у графика меты и стендингов (``services/chart_style``):
тёмный градиент, кремовый текст, золотой акцент, шрифты DejaVu.

Бейдж рисуется примитивами, а не эмодзи: в DejaVu эмодзи нет, 🏆 отрисовался бы
квадратом-тофу (та же причина, по которой клубы в подзаголовках пишутся текстом).
Медальон — кольцо цвета редкости, тёмный диск и монограмма: римская цифра уровня у
многоуровневых ачивок, первая буква названия у одноразовых. Когда появятся нарисованные
иконки, подменяется один ``_draw_badge`` — интерфейс модуля не меняется.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Sequence

from PIL import Image, ImageDraw

from services.achievements.definitions import AchievementDef, Rarity
from services.chart_style import CREAM, CREAM_DIM, GREY, WIDTH, background, draw_tracked, ellipsize, font

# Цвет кольца по редкости: чем реже — тем теплее и ярче.
RARITY_COLORS = {
    Rarity.COMMON: (0xC3, 0xCB, 0xD8),  # холодное серебро
    Rarity.RARE: (0xC4, 0xA6, 0x6A),  # золото (акцент бота)
    Rarity.EPIC: (0xD2, 0x7E, 0x57),  # медь
}
DISC = (0x1B, 0x20, 0x2A)  # тёмный диск медальона
# Закрытые заметно глуше открытых — иначе «серебро» и «нет ачивки» читаются одинаково.
LOCKED_RING = (0x30, 0x33, 0x3A)
LOCKED_DISC = (0x15, 0x18, 0x1F)
LOCKED_INK = (0x4A, 0x4E, 0x57)
SEPARATOR = (0x25, 0x27, 0x2E)

CARD_HEIGHT = 620
CARD_MARGIN = 70
BADGE_D = 260  # диаметр медальона на карточке

SHELF_COLUMNS = 3
SHELF_BADGE_D = 150
SHELF_ROW_H = 268
SHELF_TOP = 210
SHELF_MARGIN = 70

_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV"}


@dataclass(frozen=True)
class ShelfItem:
    """Одна ячейка полки: что рисуем и что подписываем.

    ``caption`` формирует вызывающий слой («открыто», «7/10», «закрыто») — рендер не
    решает, что значит прогресс.
    """

    definition: AchievementDef
    unlocked: bool
    caption: str = ""


def render_achievement_card(
    definition: AchievementDef,
    *,
    player: str,
    evidence: str = "",
    subtitle: str = "",
) -> bytes:
    """Карточка «ачивка открыта» — для отчёта и для шаринга."""
    img = background(CARD_HEIGHT)
    draw = ImageDraw.Draw(img)
    accent = RARITY_COLORS.get(definition.rarity, RARITY_COLORS[Rarity.COMMON])

    draw.rounded_rectangle((26, 26, WIDTH - 26, CARD_HEIGHT - 26), radius=22, outline=accent, width=2)

    badge_cx = CARD_MARGIN + BADGE_D // 2 + 20
    badge_cy = CARD_HEIGHT // 2
    _draw_badge(draw, badge_cx, badge_cy, BADGE_D, definition, unlocked=True)

    text_x = badge_cx + BADGE_D // 2 + 64
    text_w = WIDTH - CARD_MARGIN - text_x

    draw_tracked(
        draw,
        "АЧИВКА ОТКРЫТА",
        text_x + int(draw.textlength("АЧИВКА ОТКРЫТА", font=font("DejaVuSans.ttf", 22)) / 2) + 22,
        badge_cy - 132,
        font("DejaVuSans.ttf", 22),
        accent,
        6,
    )

    title_font = font("DejaVuSerif-Bold.ttf", 56)
    draw.text(
        (text_x, badge_cy - 78),
        ellipsize(draw, definition.title_with_level, title_font, text_w),
        font=title_font,
        fill=CREAM,
        anchor="lm",
    )

    body_font = font("DejaVuSans.ttf", 30)
    for i, line in enumerate(_wrap(draw, definition.description, body_font, text_w, limit=2)):
        draw.text((text_x, badge_cy - 16 + i * 42), line, font=body_font, fill=CREAM_DIM, anchor="lm")

    if evidence:
        small = font("DejaVuSans.ttf", 26)
        draw.line([(text_x, badge_cy + 78), (WIDTH - CARD_MARGIN, badge_cy + 78)], fill=SEPARATOR, width=1)
        for i, line in enumerate(_wrap(draw, evidence, small, text_w, limit=2)):
            draw.text((text_x, badge_cy + 112 + i * 36), line, font=small, fill=GREY, anchor="lm")

    footer = " · ".join(part for part in (player, subtitle) if part)
    if footer:
        draw.text(
            (WIDTH - CARD_MARGIN, CARD_HEIGHT - 62),
            ellipsize(draw, footer, font("DejaVuSans.ttf", 26), WIDTH - 2 * CARD_MARGIN),
            font=font("DejaVuSans.ttf", 26),
            fill=GREY,
            anchor="rm",
        )
    return _to_png(img)


def render_shelf(items: Sequence[ShelfItem], *, title: str, subtitle: str = "") -> bytes:
    """Полка ачивок: сетка медальонов, закрытые — приглушённые, с прогрессом."""
    items = list(items)
    rows = max(1, math.ceil(len(items) / SHELF_COLUMNS))
    height = SHELF_TOP + rows * SHELF_ROW_H + 60
    img = background(height)
    draw = ImageDraw.Draw(img)

    unlocked = sum(1 for item in items if item.unlocked)
    draw.text((SHELF_MARGIN, 74), title, font=font("DejaVuSerif-Bold.ttf", 52), fill=CREAM, anchor="lm")
    draw.text(
        (SHELF_MARGIN, 134),
        f"открыто {unlocked} из {len(items)}",
        font=font("DejaVuSans.ttf", 30),
        fill=GREY,
        anchor="lm",
    )
    if subtitle:
        draw.text((WIDTH - SHELF_MARGIN, 74), subtitle, font=font("DejaVuSans.ttf", 30), fill=GREY, anchor="rm")
    draw.line([(SHELF_MARGIN, 176), (WIDTH - SHELF_MARGIN, 176)], fill=SEPARATOR, width=1)

    cell_w = (WIDTH - 2 * SHELF_MARGIN) // SHELF_COLUMNS
    name_font = font("DejaVuSans-Bold.ttf", 26)
    hint_font = font("DejaVuSans.ttf", 24)
    for index, item in enumerate(items):
        column, row = index % SHELF_COLUMNS, index // SHELF_COLUMNS
        cx = SHELF_MARGIN + cell_w * column + cell_w // 2
        cy = SHELF_TOP + row * SHELF_ROW_H + SHELF_BADGE_D // 2

        _draw_badge(draw, cx, cy, SHELF_BADGE_D, item.definition, unlocked=item.unlocked)

        ink = CREAM if item.unlocked else LOCKED_INK
        name = ellipsize(draw, item.definition.title_with_level, name_font, cell_w - 24)
        draw.text((cx, cy + SHELF_BADGE_D // 2 + 34), name, font=name_font, fill=ink, anchor="mm")

        if item.caption:
            draw.text((cx, cy + SHELF_BADGE_D // 2 + 70), item.caption, font=hint_font, fill=GREY, anchor="mm")

    return _to_png(img)


def _draw_badge(draw: ImageDraw.ImageDraw, cx: int, cy: int, diameter: int, definition, *, unlocked: bool) -> None:
    """Медальон: кольцо цвета редкости, тёмный диск и монограмма по центру."""
    accent = RARITY_COLORS.get(definition.rarity, RARITY_COLORS[Rarity.COMMON]) if unlocked else LOCKED_RING
    disc = DISC if unlocked else LOCKED_DISC
    radius = diameter // 2
    ring_w = max(3, diameter // 26)

    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=disc, outline=accent, width=ring_w)
    inner = radius - ring_w * 3
    draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), outline=accent, width=1)

    if unlocked and definition.rarity == Rarity.EPIC:
        _draw_rays(draw, cx, cy, radius + ring_w * 2, accent)

    glyph = _ROMAN.get(definition.level, str(definition.level)) if definition.threshold else definition.title[:1]
    glyph_font = font("DejaVuSerif-Bold.ttf", int(diameter * 0.42))
    draw.text((cx, cy + 2), glyph, font=glyph_font, fill=accent if unlocked else LOCKED_INK, anchor="mm")


def _draw_rays(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, color: tuple) -> None:
    """Восемь коротких лучей — отличают эпические ачивки от остальных."""
    for i in range(8):
        angle = math.pi / 4 * i
        x1, y1 = cx + math.cos(angle) * (radius + 6), cy + math.sin(angle) * (radius + 6)
        x2, y2 = cx + math.cos(angle) * (radius + 20), cy + math.sin(angle) * (radius + 20)
        draw.line([(x1, y1), (x2, y2)], fill=color, width=3)


def _wrap(draw: ImageDraw.ImageDraw, text: str, text_font, max_width: int, *, limit: int) -> list[str]:
    """Разбить строку по словам под ширину; последняя строка обрезается многоточием."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=text_font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == limit:
            break
    if current and len(lines) < limit:
        lines.append(current)
    if not lines:
        return []
    lines[-1] = ellipsize(draw, lines[-1], text_font, max_width)
    return lines[:limit]


def _to_png(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
