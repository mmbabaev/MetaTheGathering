"""Dark themed 4x4 board renderer for owner bingo previews."""

from __future__ import annotations

import io

from PIL import ImageDraw

from services.achievements.bingo import BoardDraft, Category, Difficulty
from services.chart_style import CREAM, CREAM_DIM, GREY, background, ellipsize, font

BOARD_WIDTH = 1600
BOARD_HEIGHT = 1435
MARGIN = 60
GRID_TOP = 218
CELL_GAP = 16
CELL_HEIGHT = 270
CELL_WIDTH = (BOARD_WIDTH - MARGIN * 2 - CELL_GAP * 3) // 4

CARD_FILL = (0x17, 0x19, 0x20)
CARD_INNER = (0x24, 0x27, 0x30)
FOOTER = (0x69, 0x6B, 0x72)

DIFFICULTY_COLORS: dict[Difficulty, tuple[int, int, int]] = {
    Difficulty.EASY: (0x62, 0xB8, 0x91),
    Difficulty.MEDIUM: (0xC4, 0xA6, 0x6A),
    Difficulty.HARD: (0xD2, 0x7E, 0x57),
    Difficulty.RARE: (0xA9, 0x78, 0xC8),
}

DIFFICULTY_LABELS: dict[Difficulty, str] = {
    Difficulty.EASY: "ЛЕГКО",
    Difficulty.MEDIUM: "СРЕДНЕ",
    Difficulty.HARD: "СЛОЖНО",
    Difficulty.RARE: "РЕДКО",
}

CATEGORY_LABELS: dict[Category, str] = {
    Category.PARTICIPATION: "УЧАСТИЕ",
    Category.PERFORMANCE: "РЕЗУЛЬТАТ",
    Category.DECK: "КОЛОДЫ",
    Category.EXPLORATION: "ИССЛЕДОВАНИЕ",
    Category.SOCIAL: "СООБЩЕСТВО",
    Category.H2H: "ЛИЧНЫЕ ВСТРЕЧИ",
    Category.PEER_CONFIRMATION: "ПОДТВЕРЖДЕНИЕ",
}


def render_bingo_board(draft: BoardDraft, *, persona_label: str) -> bytes:
    """Render a readable Telegram PNG without changing the generated draft."""

    if draft.input.constraints.rows != 4 or draft.input.constraints.columns != 4 or len(draft.cells) != 16:
        raise ValueError("bingo preview renderer supports exactly 4x4 boards")

    image = background(BOARD_HEIGHT, width=BOARD_WIDTH)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (24, 24, BOARD_WIDTH - 24, BOARD_HEIGHT - 24),
        radius=28,
        outline=(0x34, 0x36, 0x40),
        width=2,
    )

    draw.text((MARGIN, 76), "BINGO 4×4", font=font("DejaVuSerif-Bold.ttf", 66), fill=CREAM, anchor="lm")
    draw.text(
        (MARGIN, 142),
        f"ТЕСТОВОЕ ПОЛЕ · {persona_label.upper()}",
        font=font("DejaVuSans.ttf", 27),
        fill=GREY,
        anchor="lm",
    )
    draw.text(
        (BOARD_WIDTH - MARGIN, 76),
        f"SEED {draft.input.seed}",
        font=font("DejaVuSans-Bold.ttf", 30),
        fill=CREAM_DIM,
        anchor="rm",
    )
    draw.text(
        (BOARD_WIDTH - MARGIN, 142),
        f"{draft.input.catalog_version} · {draft.input.algorithm_version}",
        font=font("DejaVuSans.ttf", 23),
        fill=GREY,
        anchor="rm",
    )
    draw.line([(MARGIN, 184), (BOARD_WIDTH - MARGIN, 184)], fill=(0x2B, 0x2D, 0x35), width=2)

    for cell in draft.cells:
        x = MARGIN + cell.column * (CELL_WIDTH + CELL_GAP)
        y = GRID_TOP + cell.row * (CELL_HEIGHT + CELL_GAP)
        _draw_cell(draw, x, y, cell.index + 1, cell.candidate)

    draw.text(
        (MARGIN, BOARD_HEIGHT - 55),
        "PREVIEW · только горизонтальные линии · поле не сохранено",
        font=font("DejaVuSans.ttf", 23),
        fill=FOOTER,
        anchor="lm",
    )
    draw.text(
        (BOARD_WIDTH - MARGIN, BOARD_HEIGHT - 55),
        draft.input.candidate_fingerprint[:12].upper(),
        font=font("DejaVuSans.ttf", 23),
        fill=FOOTER,
        anchor="rm",
    )

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _draw_cell(draw: ImageDraw.ImageDraw, x: int, y: int, number: int, candidate) -> None:
    accent = DIFFICULTY_COLORS[candidate.difficulty]
    draw.rounded_rectangle(
        (x, y, x + CELL_WIDTH, y + CELL_HEIGHT),
        radius=22,
        fill=CARD_FILL,
        outline=accent,
        width=3,
    )
    draw.rounded_rectangle(
        (x + 10, y + 10, x + CELL_WIDTH - 10, y + CELL_HEIGHT - 10),
        radius=16,
        outline=CARD_INNER,
        width=1,
    )

    meta_font = font("DejaVuSans-Bold.ttf", 20)
    draw.text((x + 22, y + 28), f"{number:02}", font=meta_font, fill=accent, anchor="lm")
    draw.text(
        (x + CELL_WIDTH - 22, y + 28),
        DIFFICULTY_LABELS[candidate.difficulty],
        font=meta_font,
        fill=accent,
        anchor="rm",
    )

    title_font = font("DejaVuSerif-Bold.ttf", 31)
    title_lines = _wrap(draw, candidate.title, title_font, CELL_WIDTH - 44, max_lines=2)
    for index, line in enumerate(title_lines):
        draw.text((x + 22, y + 66 + index * 38), line, font=title_font, fill=CREAM, anchor="lm")

    divider_y = y + 140
    draw.line([(x + 22, divider_y), (x + CELL_WIDTH - 22, divider_y)], fill=CARD_INNER, width=1)
    hint_font = font("DejaVuSans.ttf", 22)
    for index, line in enumerate(_wrap(draw, candidate.hint, hint_font, CELL_WIDTH - 44, max_lines=3)):
        draw.text((x + 22, divider_y + 27 + index * 29), line, font=hint_font, fill=CREAM_DIM, anchor="lm")

    draw.text(
        (x + 22, y + CELL_HEIGHT - 23),
        CATEGORY_LABELS[candidate.category],
        font=font("DejaVuSans.ttf", 17),
        fill=GREY,
        anchor="lm",
    )


def _wrap(draw: ImageDraw.ImageDraw, text: str, text_font, max_width: int, *, max_lines: int) -> list[str]:
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
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if not lines:
        return []
    lines[-1] = ellipsize(draw, lines[-1], text_font, max_width)
    return lines[:max_lines]
