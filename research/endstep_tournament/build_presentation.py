"""Build the Russian Endstep tournament research deck."""

from __future__ import annotations

import json
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / "data.json").read_text(encoding="utf-8"))
OUT = ROOT / "endstep_tournament_report.pptx"

W, H = 13.333, 7.5
BG = "10141C"
PANEL = "1D2633"
PANEL_2 = "253244"
WHITE = "F7F3E8"
MUTED = "AAB3C2"
GOLD = "D6A928"
CYAN = "4FC3B3"
BLUE = "5591E6"
RED = "E4553D"
GREEN = "55C787"
PURPLE = "B68CFF"


def rgb(value: str) -> RGBColor:
    return RGBColor.from_string(value)


def box(slide, x, y, w, h, fill=PANEL, line=None, radius=True):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x),
        Inches(y),
        Inches(w),
        Inches(h),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    shape.line.color.rgb = rgb(line or fill)
    shape.line.width = Pt(1.2)
    return shape


def text(slide, value, x, y, w, h, size=16, color=WHITE, bold=False, align=PP_ALIGN.LEFT, font="Aptos"):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Inches(0.03)
    tf.margin_right = Inches(0.03)
    tf.margin_top = Inches(0.02)
    tf.margin_bottom = Inches(0.02)
    tf.vertical_anchor = MSO_ANCHOR.TOP
    p = tf.paragraphs[0]
    p.alignment = align
    p.space_after = Pt(0)
    run = p.add_run()
    run.text = value
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = rgb(color)
    return shape


def bullet_text(slide, lines, x, y, w, h, size=16, color=WHITE, gap=5):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Inches(0.04)
    tf.margin_right = Inches(0.04)
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = "• " + line
        p.level = 0
        p.space_after = Pt(gap)
        p.font.name = "Aptos"
        p.font.size = Pt(size)
        p.font.color.rgb = rgb(color)
    return shape


def bg(slide):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = rgb(BG)


def header(slide, kicker, title_value, page):
    text(slide, kicker.upper(), 0.65, 0.30, 5.8, 0.25, 10, GOLD, True)
    text(slide, title_value, 0.65, 0.67, 12.0, 0.55, 27, WHITE, True)
    text(slide, f"ENDSTEP · {page:02d}", 11.65, 0.34, 1.0, 0.25, 9, MUTED, True, PP_ALIGN.RIGHT)


def footer(slide):
    text(
        slide, "MetaGatherer research · 03.10.2026 · агрегаты без персональных данных", 0.67, 7.16, 8.0, 0.18, 8, MUTED
    )


def metric(slide, x, y, value, label, color, width=2.6):
    box(slide, x, y, width, 1.12, PANEL, color)
    text(slide, value, x + 0.18, y + 0.15, width - 0.36, 0.42, 25, color, True)
    text(slide, label, x + 0.18, y + 0.68, width - 0.36, 0.25, 10, MUTED)


def add_slide(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg(slide)
    return slide


def build():
    prs = Presentation()
    prs.slide_width = Inches(W)
    prs.slide_height = Inches(H)

    # 1. Title
    s = add_slide(prs)
    text(s, "ENDSTEP · ИССЛЕДОВАНИЕ", 0.76, 0.62, 5, 0.3, 11, GOLD, True)
    text(s, "Стилёк x Концеход\n@ Endstep", 0.72, 1.35, 7.4, 1.55, 36, WHITE, True)
    text(s, "Метагейм турнира · Top 8 · deck choice · удача в парингах", 0.78, 3.18, 8.3, 0.35, 17, MUTED)
    metric(s, 0.78, 4.55, "104", "игрока в публичном результате", CYAN, 2.35)
    metric(s, 3.35, 4.55, "7", "раундов Swiss", BLUE, 2.15)
    metric(s, 5.70, 4.55, "8", "колод в Top 8", GOLD, 2.15)
    box(s, 9.15, 0.75, 3.45, 5.85, PANEL, GOLD)
    text(s, "1", 9.53, 1.24, 0.8, 0.9, 55, GOLD, True, PP_ALIGN.CENTER)
    text(s, "Orzhov\nGlintblade", 10.15, 1.37, 2.1, 0.9, 25, WHITE, True)
    text(s, "Победитель\n6–1 в Swiss\n2–1 в финале", 9.53, 2.85, 2.65, 1.0, 18, CYAN, True, PP_ALIGN.CENTER)
    text(
        s,
        "Публичные результаты +\nрегистрационный срез MetaGatherer",
        9.53,
        5.37,
        2.65,
        0.6,
        12,
        MUTED,
        align=PP_ALIGN.CENTER,
    )
    footer(s)

    # 2. Tournament in numbers
    s = add_slide(prs)
    header(s, "01 · контекст", "Турнир в цифрах", 2)
    metrics = [
        ("104", "участника", CYAN),
        ("7", "Swiss-раундов", BLUE),
        ("272", "сыгранных Swiss-матча", GOLD),
        ("8", "разных архетипов в Top 8", GREEN),
        ("2", "Affinity в Top 4", RED),
        ("7–0", "лучший Swiss", PURPLE),
    ]
    for i, (v, label, c) in enumerate(metrics):
        x = 0.72 + (i % 3) * 4.15
        y = 1.72 + (i // 3) * 1.55
        metric(s, x, y, v, label, c, 3.55)
    box(s, 0.72, 5.25, 11.9, 1.05, PANEL_2, PANEL_2)
    text(s, "Сигнал турнира", 1.00, 5.47, 1.65, 0.25, 12, GOLD, True)
    text(
        s,
        "Поле не свелось к одной tier-колоде: специализированные планы получили реальный результат.",
        2.75,
        5.42,
        9.4,
        0.35,
        18,
        WHITE,
        True,
    )
    footer(s)

    # 3. Data quality
    s = add_slide(prs)
    header(s, "02 · качество данных", "Сначала — важная оговорка", 3)
    box(s, 0.72, 1.55, 5.7, 4.95, PANEL, GOLD)
    text(s, "Что есть в БД", 1.05, 1.92, 3, 0.3, 18, GOLD, True)
    bullet_text(
        s,
        [
            "113 регистраций",
            "110 записей с указанной колодой",
            "91 записи с заполненным general_name",
            "22 записи не нормализованы",
        ],
        1.08,
        2.55,
        4.85,
        2.0,
        18,
    )
    box(s, 6.82, 1.55, 5.8, 4.95, PANEL, RED)
    text(s, "Как соединили источники", 7.15, 1.92, 4.2, 0.3, 18, RED, True)
    bullet_text(
        s,
        [
            "БД: метагейм и названия колод",
            "Endstep: 284 Swiss pairing rows",
            "272 reported-матча после исключения no-show",
            "23 decklists классифицированы вручную по семейству",
        ],
        7.18,
        2.55,
        4.9,
        2.35,
        17,
    )
    text(
        s,
        "Production-БД ещё не финализировала турнир; поэтому результаты матчей берём из полной страницы Endstep.",
        0.9,
        6.78,
        11.5,
        0.3,
        14,
        CYAN,
        True,
        PP_ALIGN.CENTER,
    )
    footer(s)

    # 4. Full field metagame bars
    s = add_slide(prs)
    header(s, "03 · метагейм", "Реальное поле: 104 деклиста", 4)
    text(s, "семейства стратегий · полный Swiss-срез", 0.75, 1.35, 4.0, 0.25, 11, MUTED)
    bars = sorted(DATA["full_swiss_meta"], key=lambda row: row[1], reverse=True)[:10]
    max_n = max(row[1] for row in bars)
    for i, row in enumerate(bars):
        name, n, _, _, _ = row
        y = 1.78 + i * 0.39
        text(s, name, 0.78, y, 2.35, 0.22, 11, WHITE)
        box(s, 3.25, y + 0.01, 6.65 * n / max_n, 0.23, BLUE, BLUE, False)
        text(s, str(n), 10.08, y - 0.01, 0.5, 0.22, 11, WHITE, True)
    box(s, 10.85, 1.58, 1.72, 4.95, PANEL, PANEL_2)
    text(s, "Редкие\nсигналы", 11.12, 1.88, 1.2, 0.55, 17, GOLD, True, PP_ALIGN.CENTER)
    text(
        s,
        "Sultai Fog\nNaya Gates\nUR Kiln Fiend\nTemur Rogue\nWhite Heroic\nWR Tribe\nMardu Synth",
        11.08,
        2.85,
        1.25,
        2.35,
        13,
        WHITE,
        align=PP_ALIGN.CENTER,
    )
    text(s, "по 1 записи", 11.12, 5.7, 1.2, 0.25, 10, MUTED, align=PP_ALIGN.CENTER)
    footer(s)

    # 5. Swiss winrates
    s = add_slide(prs)
    header(s, "04 · Swiss", "Винрейты колод в полном поле", 5)
    text(
        s,
        "MWR = match win rate · только 272 сыгранных Swiss-матча · малые выборки читать осторожно",
        0.75,
        1.32,
        8.9,
        0.25,
        11,
        MUTED,
    )
    swiss = sorted(DATA["full_swiss_meta"], key=lambda row: row[4], reverse=True)
    columns = [swiss[:7], swiss[7:]]
    for col, rows in enumerate(columns):
        x = 0.72 + col * 6.0
        box(s, x, 1.72, 5.55, 4.75, PANEL, PANEL_2)
        text(
            s,
            "СИЛЬНЕЕ СРЕДНЕГО" if col == 0 else "СЛАБЕЕ / НЕСТАБИЛЬНЕЕ",
            x + 0.28,
            1.98,
            4.8,
            0.25,
            12,
            GREEN if col == 0 else RED,
            True,
        )
        for i, (name, field_n, match_n, wl, mwr) in enumerate(rows):
            y = 2.43 + i * 0.53
            text(s, name, x + 0.28, y, 1.58, 0.23, 12, WHITE, True)
            text(s, f"{field_n} · {match_n} матчей", x + 1.88, y, 1.55, 0.23, 10, MUTED)
            box(
                s,
                x + 3.57,
                y + 0.02,
                1.05 * min(mwr, 70) / 70,
                0.18,
                GREEN if mwr >= 50 else RED,
                GREEN if mwr >= 50 else RED,
                False,
            )
            text(s, f"{wl}  {mwr:.1f}%", x + 4.62, y - 0.02, 0.65, 0.23, 10, WHITE, True, PP_ALIGN.RIGHT)
    box(s, 1.12, 6.65, 11.05, 0.38, PANEL_2, PANEL_2)
    text(
        s,
        "Лучшие устойчивые сигналы: Blue Terror 66.7%, Bogles 65.0%, Spy 62.5% · Affinity — 53.5% при 9 участниках",
        1.32,
        6.74,
        10.65,
        0.18,
        11,
        WHITE,
        True,
        PP_ALIGN.CENTER,
    )
    footer(s)

    # 6. MTGDecks benchmark
    s = add_slide(prs)
    header(s, "05 · benchmark", "Турнирный MWR против MTGDecks", 6)
    text(
        s,
        "MTGDecks: Overall · ALL · 180 дней и 30 дней · проценты округлены как на сайте",
        0.75,
        1.32,
        8.6,
        0.25,
        11,
        MUTED,
    )
    box(s, 0.72, 1.68, 11.9, 4.98, PANEL, PANEL_2)
    text(s, "СЕМЕЙСТВО", 1.0, 1.94, 2.0, 0.2, 10, GOLD, True)
    text(s, "N", 3.4, 1.94, 0.35, 0.2, 10, GOLD, True, PP_ALIGN.RIGHT)
    text(s, "ENDSTEP", 4.18, 1.94, 0.72, 0.2, 10, GOLD, True, PP_ALIGN.RIGHT)
    text(s, "180D", 5.65, 1.94, 0.55, 0.2, 10, GOLD, True, PP_ALIGN.RIGHT)
    text(s, "30D", 6.75, 1.94, 0.55, 0.2, 10, GOLD, True, PP_ALIGN.RIGHT)
    text(s, "Δ", 7.88, 1.94, 0.45, 0.2, 10, GOLD, True, PP_ALIGN.RIGHT)
    text(s, "MTGDecks proxy", 8.78, 1.94, 2.6, 0.2, 10, GOLD, True)
    for i, (name, field_n, _, local, rate_180, rate_30, proxy) in enumerate(DATA["mtgdecks_benchmark"]["rows"]):
        y = 2.28 + i * 0.35
        delta = local - rate_180
        if i % 2 == 0:
            box(s, 0.94, y - 0.03, 11.35, 0.28, PANEL_2, PANEL_2, False)
        text(s, name, 1.0, y, 2.12, 0.18, 10, WHITE, True)
        text(s, str(field_n), 3.4, y, 0.35, 0.18, 10, WHITE, True, PP_ALIGN.RIGHT)
        text(s, f"{local:.1f}%", 4.18, y, 0.72, 0.18, 10, WHITE, True, PP_ALIGN.RIGHT)
        text(s, f"{rate_180:.1f}%", 5.65, y, 0.55, 0.18, 10, MUTED, align=PP_ALIGN.RIGHT)
        text(s, f"{rate_30:.1f}%", 6.75, y, 0.55, 0.18, 10, MUTED, align=PP_ALIGN.RIGHT)
        text(s, f"{delta:+.1f}", 7.88, y, 0.45, 0.18, 10, GREEN if delta >= 0 else RED, True, PP_ALIGN.RIGHT)
        text(s, proxy, 8.78, y, 3.0, 0.18, 9, MUTED)
    text(
        s,
        "Сильное совпадение: Affinity +1.4 п.п. · главный локальный разрыв: RG Ramp −24.1 п.п. и Tron −19.2 п.п.",
        0.9,
        6.82,
        11.5,
        0.22,
        12,
        WHITE,
        True,
        PP_ALIGN.CENTER,
    )
    footer(s)

    # 7. Winner/finalist
    s = add_slide(prs)
    header(s, "06 · deck choice", "Победитель и финалист", 7)
    box(s, 0.72, 1.45, 5.8, 4.95, PANEL, GOLD)
    text(s, "1 · ORZHOV GLINTBLADE", 1.02, 1.78, 4.8, 0.3, 17, GOLD, True)
    text(s, "6–1 Swiss · финал 2–1", 1.02, 2.18, 4.6, 0.3, 17, CYAN, True)
    bullet_text(
        s,
        [
            "4 Glint Hawk · 4 Kor Skyfisher",
            "4 Refurbished Familiar · 4 Lembas",
            "4 Dispatch · 4 Thraben Charm",
            "side: 4 Dust to Dust + 3 Temporal Intervention",
        ],
        1.02,
        2.85,
        4.9,
        1.75,
        16,
    )
    text(
        s, "Value + tempo + широкий removal. Sideboard прямо уважает Affinity.", 1.02, 5.55, 4.9, 0.45, 15, WHITE, True
    )
    box(s, 6.82, 1.45, 5.8, 4.95, PANEL, CYAN)
    text(s, "2 · IZZET SKRED", 7.12, 1.78, 4.8, 0.3, 17, CYAN, True)
    text(s, "6–1 Swiss · финал 1–2", 7.12, 2.18, 4.6, 0.3, 17, GOLD, True)
    bullet_text(
        s,
        [
            "4 Skred · 4 Counterspell · 4 Spell Pierce",
            "4 Brainstorm · 4 Lórien Revealed",
            "4 Plunder the Trollshaws",
            "side: 4 Hydroblast · 4 Pyroblast · 3 Vandalblast",
        ],
        7.12,
        2.85,
        4.9,
        1.75,
        16,
    )
    text(s, "Контроль темпа: дешёвые ответы и много card selection.", 7.12, 5.55, 4.9, 0.45, 15, WHITE, True)
    footer(s)

    # 8. Affinity
    s = add_slide(prs)
    header(s, "07 · overperformance", "Affinity — главный мета-сигнал", 8)
    metric(s, 0.78, 1.55, "7 / 113", "Affinity в регистрациях", BLUE, 3.0)
    metric(s, 4.10, 1.55, "2 / 8", "Affinity в Top 8", RED, 3.0)
    metric(s, 7.42, 1.55, "4×", "примерный uplift доли", GOLD, 3.0)
    box(s, 0.78, 3.15, 5.75, 2.85, PANEL, BLUE)
    text(s, "Dimir Affinity", 1.08, 3.48, 4.8, 0.3, 20, BLUE, True)
    text(
        s,
        "Myr Enforcer · Refurbished Familiar\nThoughtcast · Reckoner's Bargain\nGiant's Boulder\n\n3–4 место",
        1.08,
        4.02,
        4.8,
        1.35,
        16,
        WHITE,
    )
    box(s, 6.82, 3.15, 5.75, 2.85, PANEL, RED)
    text(s, "Grixis Affinity", 7.12, 3.48, 4.8, 0.3, 20, RED, True)
    text(
        s,
        "Myr Enforcer · Refurbished Familiar\nUtrom Monitor · Thoughtcast\nCast Down · discard\n\n3–4 место",
        7.12,
        4.02,
        4.8,
        1.35,
        16,
        WHITE,
    )
    footer(s)

    # 9. Rogue top8
    s = add_slide(prs)
    header(s, "08 · rogue decks", "Самые интересные малопопулярные колоды", 9)
    rogue = [
        ("Aura Hexproof", "7–0 Swiss", "4 Bogle · 4 Scout · 4 Rancor · 4 Cloak · 4 Mask", GOLD),
        ("Balustrade Spy", "Top 8", "4 Spy · 4 Land Grant · 4 Winding Way · 3 Petal", PURPLE),
        ("Simic Petitioners", "Top 8", "11 Petitioners · 4 Glistener Seer · mill engine", CYAN),
    ]
    for i, (name, record, core, color) in enumerate(rogue):
        x = 0.72 + i * 4.18
        box(s, x, 1.65, 3.72, 4.55, PANEL, color)
        text(s, name, x + 0.28, 2.02, 3.1, 0.55, 20, color, True)
        text(s, record, x + 0.28, 2.78, 3.0, 0.3, 17, WHITE, True)
        text(s, core, x + 0.28, 3.42, 3.1, 1.0, 16, WHITE)
        text(s, "Почему интересно", x + 0.28, 4.78, 2.8, 0.25, 11, MUTED, True)
        descriptions = [
            "Линейная колода наказывает отсутствие edict и массовых ответов.",
            "Комбо с экстремально низкой земельной базой.",
            "Неожиданный tribal/engine-план с 11 Persistent Petitioners.",
        ]
        text(s, descriptions[i], x + 0.28, 5.12, 3.05, 0.68, 13, WHITE)
    footer(s)

    # 10. Champion Swiss path
    s = add_slide(prs)
    header(s, "09 · Swiss path", "Кого побеждал чемпион в 7 раундах", 10)
    text(
        s,
        "Orzhov Glintblade · итог 6–1 · в скобках — итоговый Swiss-рекорд соперника",
        0.78,
        1.32,
        8.5,
        0.25,
        12,
        MUTED,
    )
    box(s, 0.78, 1.78, 11.78, 4.8, PANEL, GOLD)
    text(s, "РАУНД", 1.05, 2.04, 0.75, 0.2, 10, GOLD, True)
    text(s, "СОПЕРНИК", 2.08, 2.04, 3.2, 0.2, 10, GOLD, True)
    text(s, "РЕЗУЛЬТАТ", 8.9, 2.04, 1.2, 0.2, 10, GOLD, True)
    text(s, "ФИНИШ СОПЕРНИКА", 10.25, 2.04, 1.8, 0.2, 10, GOLD, True)
    for i, (round_no, opponent, result, record) in enumerate(DATA["champion_swiss_path"]):
        y = 2.42 + i * 0.51
        if i % 2 == 0:
            box(s, 1.0, y - 0.05, 11.15, 0.34, PANEL_2, PANEL_2, False)
        text(s, str(round_no), 1.08, y, 0.35, 0.2, 13, WHITE, True)
        text(s, opponent, 2.08, y, 5.8, 0.2, 13, WHITE)
        text(s, result, 9.15, y, 0.5, 0.2, 13, GREEN if result == "W" else RED, True)
        text(s, record, 11.0, y, 0.75, 0.2, 13, WHITE, True, PP_ALIGN.RIGHT)
    text(
        s,
        "Расписание не было пустым: 3 из 7 соперников закончили Swiss с результатом 5–2 или лучше; единственное поражение — Affinity 6–1.",
        1.0,
        6.78,
        11.3,
        0.25,
        13,
        WHITE,
        True,
        PP_ALIGN.CENTER,
    )
    footer(s)

    # 11. Top8 OMW
    s = add_slide(prs)
    header(s, "10 · Top 8", "Результат объясняет не только удача", 11)
    text(s, "Официальная Swiss-таблица Top 8 · OMW = сила расписания", 0.78, 1.32, 7.0, 0.25, 12, MUTED)
    box(s, 0.78, 1.75, 7.9, 4.85, PANEL, PANEL_2)
    text(s, "МЕСТО", 1.08, 2.02, 0.65, 0.2, 10, GOLD, True)
    text(s, "КОЛОДА", 1.9, 2.02, 3.3, 0.2, 10, GOLD, True)
    text(s, "SWISS", 5.75, 2.02, 0.8, 0.2, 10, GOLD, True)
    text(s, "OMW", 7.35, 2.02, 0.7, 0.2, 10, GOLD, True)
    for i, (place, deck, record, omw) in enumerate(DATA["top8_swiss"]):
        y = 2.43 + i * 0.48
        if i % 2 == 0:
            box(s, 1.0, y - 0.04, 7.35, 0.32, PANEL_2, PANEL_2, False)
        text(s, str(place), 1.1, y, 0.35, 0.2, 13, GOLD if place == 1 else WHITE, True)
        text(s, deck, 1.9, y, 3.55, 0.2, 13, WHITE, place == 1)
        text(s, record, 5.75, y, 0.8, 0.2, 13, WHITE, True)
        text(s, f"{omw:.2f}%", 7.35, y, 0.8, 0.2, 13, CYAN if omw >= 63 else WHITE, True, PP_ALIGN.RIGHT)
    box(s, 9.05, 1.75, 3.5, 4.85, PANEL, CYAN)
    text(s, "Что важно", 9.4, 2.08, 2.7, 0.3, 19, CYAN, True)
    bullet_text(
        s,
        [
            "У чемпиона OMW 60.27% — не лёгкое расписание.",
            "У Petitioners OMW 77.55% — самый сильный Swiss среди Top 8.",
            "7–0 Blue Terror не конвертировал преимущество в Top 4.",
        ],
        9.38,
        2.75,
        2.75,
        2.45,
        15,
    )
    footer(s)

    # 12. Confirmed facts and insights
    s = add_slide(prs)
    header(s, "11 · инсайты", "Что подтверждено — и что удивляет", 12)
    insight_cards = [
        (
            "ПОДТВЕРЖДЕНО",
            "Affinity",
            "53.5% здесь и около 52% у MTGDecks: стратегия действительно сильна, но её Top 8 — это конвертация, а не тотальное доминирование.",
            RED,
        ),
        (
            "НЕОЖИДАННО",
            "Tron / RG Ramp",
            "31.4% и 26.9% в турнире против примерно 50% снаружи. Локальное поле оказалось для этих планов очень жёстким.",
            GOLD,
        ),
        (
            "ЛОКАЛЬНЫЙ SPIKE",
            "Blue Terror / Bogles",
            "66.7% и 65.0% против 49–52% в коротком benchmark. Сильный результат, но 33 и 20 матчей не заменяют длинную дистанцию.",
            CYAN,
        ),
        (
            "ФАКТ О TOP 8",
            "Petitioners",
            "5–2 при OMW 77.55% — самый сильный Swiss-срез Top 8. Это не лёгкая ветка, а настоящий rogue-результат.",
            PURPLE,
        ),
    ]
    for i, (kicker, title, body, color) in enumerate(insight_cards):
        x = 0.72 + (i % 2) * 6.0
        y = 1.58 + (i // 2) * 2.55
        box(s, x, y, 5.55, 2.05, PANEL, color)
        text(s, kicker, x + 0.3, y + 0.28, 4.8, 0.2, 10, color, True)
        text(s, title, x + 0.3, y + 0.62, 4.8, 0.3, 20, WHITE, True)
        text(s, body, x + 0.3, y + 1.1, 4.85, 0.68, 13, WHITE)
    text(
        s,
        "Главный вывод: общий benchmark объясняет направление, но не заменяет matchup-структуру конкретного турнира.",
        0.9,
        6.78,
        11.5,
        0.25,
        14,
        WHITE,
        True,
        PP_ALIGN.CENTER,
    )
    footer(s)

    # 13. playoff path
    s = add_slide(prs)
    header(s, "12 · bracket", "Кого побеждали в Top 8", 13)
    text(s, "Публичный bracket · это не полный список Swiss-матчей", 0.78, 1.32, 6.5, 0.25, 12, MUTED)
    path = [
        ("1/4", "Aura Hexproof", "2–0", GOLD),
        ("1/2", "Balustrade Spy", "2–1", PURPLE),
        ("Финал", "Izzet Skred", "2–1", CYAN),
    ]
    for i, (stage, opponent, score, color) in enumerate(path):
        x = 0.9 + i * 4.08
        box(s, x, 2.12, 3.4, 2.7, PANEL, color)
        text(s, stage.upper(), x + 0.28, 2.42, 1.2, 0.25, 11, color, True)
        text(s, "ORZHOV\nGLINTBLADE", x + 0.28, 2.9, 2.6, 0.62, 19, WHITE, True)
        text(s, "vs " + opponent, x + 0.28, 3.82, 2.7, 0.35, 16, MUTED)
        text(s, score, x + 2.47, 2.42, 0.62, 0.38, 20, color, True, PP_ALIGN.RIGHT)
        if i < 2:
            text(s, "→", x + 3.52, 3.1, 0.5, 0.45, 28, MUTED, True, PP_ALIGN.CENTER)
    box(s, 0.9, 5.45, 11.42, 0.8, PANEL_2, PANEL_2)
    text(
        s,
        "Параллельная ветка: Dimir Affinity 2–1 Mono Blue Terror · Grixis Affinity 2–0 Petitioners · Izzet Skred 2–0 Spy и 2–1 Grixis Affinity",
        1.18,
        5.68,
        10.85,
        0.28,
        12,
        WHITE,
        align=PP_ALIGN.CENTER,
    )
    footer(s)

    # 14. luck
    s = add_slide(prs)
    header(s, "13 · интерпретация", "Насколько повезло с парингами", 14)
    box(s, 0.78, 1.55, 5.72, 4.85, PANEL, GOLD)
    text(s, "В пользу удачи", 1.1, 1.9, 3.2, 0.3, 19, GOLD, True)
    bullet_text(
        s,
        [
            "0 из 2 Affinity в пути чемпиона",
            "Affinity заняла половину Top 4",
            "В четвертьфинале — Aura, а не Affinity",
        ],
        1.1,
        2.55,
        4.8,
        1.65,
        18,
    )
    box(s, 6.83, 1.55, 5.72, 4.85, PANEL, CYAN)
    text(s, "В пользу качества", 7.15, 1.9, 3.2, 0.3, 19, CYAN, True)
    bullet_text(
        s,
        [
            "2–1 над Spy и 2–1 в финале",
            "4 Dust to Dust заранее закрывают Affinity",
            "Swiss 6–1 подтверждает стабильность",
        ],
        7.15,
        2.55,
        4.8,
        1.65,
        18,
    )
    text(
        s,
        "Итог: bracket был благоприятным, но «случайной победой» результат не выглядит.",
        1.0,
        6.8,
        11.2,
        0.28,
        16,
        WHITE,
        True,
        PP_ALIGN.CENTER,
    )
    footer(s)

    # 15. conclusion
    s = add_slide(prs)
    header(s, "14 · вывод", "Что забираем из турнира", 15)
    conclusions = [
        ("01", "Deck choice", "Orzhov Glintblade — рациональный выбор против артефактов и creature-heavy поля.", GOLD),
        ("02", "Главный сигнал", "Affinity: 2 из 8 Top 8 при 7 регистрациях из 113.", RED),
        ("03", "Rogue", "Petitioners, Spy и Aura показали, что узкий план может конвертироваться в результат.", PURPLE),
        ("04", "Следующий шаг", "Сохранить Swiss pairings в БД и повторять такой matchup-анализ автоматически.", CYAN),
    ]
    for i, (num, head, body, color) in enumerate(conclusions):
        y = 1.55 + i * 1.24
        text(s, num, 0.82, y + 0.06, 0.5, 0.35, 17, color, True)
        text(s, head, 1.55, y, 2.0, 0.3, 18, color, True)
        text(s, body, 3.55, y, 8.55, 0.45, 17, WHITE)
        box(s, 1.55, y + 0.72, 10.55, 0.015, PANEL_2, PANEL_2, False)
    text(
        s,
        "Источники: MTGTop8 · публичный Endstep result · агрегаты MetaGatherer",
        0.85,
        6.6,
        11.5,
        0.3,
        14,
        MUTED,
        align=PP_ALIGN.CENTER,
    )
    footer(s)

    prs.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build()
