"""Общий визуальный стиль картинок бота (график метагейма, стендинги).

Тёмная тема, кремовый текст, золотой акцент, шрифты DejaVu. Держим в одном месте, чтобы
все картинки читались как одна система, а не как разные поделки.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

WIDTH = 1179

BG_TOP = (0x16, 0x17, 0x1C)
BG_BOTTOM = (0x0D, 0x0E, 0x13)
CREAM = (0xFC, 0xFB, 0xF6)
CREAM_DIM = (0xF3, 0xEF, 0xE4)
GREY = (0x9F, 0x9E, 0x99)
GOLD = (0xC4, 0xA6, 0x6A)
SEPARATOR = (0x21, 0x22, 0x27)
FOOTER_GREY = (0x4E, 0x50, 0x58)

# Клуб в подзаголовке — текстом: эмодзи (🦄/🐠) в DejaVu нет, вышли бы квадраты-тофу.
CLUB_NAMES = {"edinorog": "Единорог", "goldfish": "Goldfish"}

# Дату берём из названия турнира («Pauper 13.07.2026») — это дата самого турнира,
# а created_at может отличаться (турнир заводят заранее или задним числом).
_DATE_IN_TITLE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")


def font(filename: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_FONT_DIR / filename), size)


def background(height: int, width: int = WIDTH) -> Image.Image:
    """Фон с вертикальным градиентом."""
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(height - 1, 1)
        color = tuple(round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color)
    return img


def draw_tracked(
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


def ellipsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    """Обрезает длинный текст многоточием под доступную ширину."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


def build_subtitle(club: Optional[str], title: str, fallback_date: Optional[datetime] = None) -> str:
    """Подзаголовок «Единорог · 13.07.2026». Пустая строка — если нечего показать."""
    match = _DATE_IN_TITLE_RE.search(title or "")
    date = match.group(1) if match else (fallback_date.strftime("%d.%m.%Y") if fallback_date else None)
    club_name = CLUB_NAMES.get((club or "").strip().lower()) or (club or "").strip() or None
    return " · ".join(part for part in (club_name, date) if part)
