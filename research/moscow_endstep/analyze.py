"""Generate the study charts from anonymized research CSV files.

The checked-in candidate datasets use local labels (C01–C11 and F01–F19).
Names, usernames, Telegram IDs, and profile cities are intentionally excluded.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CHARTS = ROOT / "charts"
PRICE_CHANGE_DATE = date(2026, 9, 1)
ENDSTEP_START_DATE = date(2026, 9, 5)


def esc(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def svg_start(width: int, height: int, title: str, subtitle: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#243447}.title{font-size:25px;font-weight:700}.subtitle{font-size:14px;fill:#52616b}.label{font-size:14px;font-weight:600}.small{font-size:12px}.axis{stroke:#8b99a5;stroke-width:1}.grid{stroke:#e4e9ee;stroke-width:1}</style>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="48" y="38" class="title">{esc(title)}</text>',
        f'<text x="48" y="63" class="subtitle">{esc(subtitle)}</text>',
    ]


def finish(lines: list[str]) -> str:
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def load_events() -> list[dict[str, str]]:
    with (DATA / "events.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_candidates() -> list[dict[str, str]]:
    with (DATA / "switch_candidates.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_goldfish_events() -> list[dict[str, str]]:
    with (DATA / "goldfish_events.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_candidate_goldfish() -> list[dict[str, str]]:
    with (DATA / "candidate_goldfish.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_edinorog_goldfish_flow() -> list[dict[str, str]]:
    with (DATA / "edinorog_goldfish_flow.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def attendance_chart(events: list[dict[str, str]]) -> str:
    rows = [row for row in events if row["track"] == "edinorog_monday"]
    values = [int(row["participants"]) for row in rows]
    width, height = 1200, 650
    left, right, top, bottom = 78, 42, 100, 485
    plot_w, plot_h = width - left - right, bottom - top
    max_value = 80
    x_step = plot_w / (len(values) - 1)

    def x(index: int) -> float:
        return left + index * x_step

    start_date = date.fromisoformat(rows[0]["event_date"])
    end_date = date.fromisoformat(rows[-1]["event_date"])

    def date_x(value: date) -> float:
        fraction = (value - start_date).days / (end_date - start_date).days
        return left + fraction * plot_w

    def y(value: float) -> float:
        return bottom - value / max_value * plot_h

    lines = svg_start(
        width,
        height,
        "Понедельники «Единорога»: цена и запуск Endstep",
        "Записи участников; оранжевая линия — повышение цены 01.09, красная — первый обычный Endstep 05.09.",
    )
    for tick in range(0, max_value + 1, 20):
        yy = y(tick)
        lines.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{width - right}" y2="{yy:.1f}" class="grid"/>')
        lines.append(f'<text x="{left - 12}" y="{yy + 4:.1f}" text-anchor="end" class="small">{tick}</text>')
    lines.append(f'<line x1="{left}" y1="{bottom}" x2="{width - right}" y2="{bottom}" class="axis"/>')
    lines.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" class="axis"/>')

    price_x = date_x(PRICE_CHANGE_DATE)
    endstep_x = date_x(ENDSTEP_START_DATE)
    lines.append(
        f'<rect x="{price_x:.1f}" y="{top}" width="{width - right - price_x:.1f}" height="{plot_h}" fill="#fff7ed"/>'
    )
    lines.append(
        f'<line x1="{price_x:.1f}" y1="{top - 12}" x2="{price_x:.1f}" y2="{bottom + 34}" stroke="#ea580c" stroke-width="2" stroke-dasharray="5 5"/>'
    )
    lines.append(
        f'<text x="{price_x - 8:.1f}" y="{top - 18}" text-anchor="end" class="label" fill="#c2410c">Цена: 01.09</text>'
    )
    lines.append(
        f'<line x1="{endstep_x:.1f}" y1="{top - 12}" x2="{endstep_x:.1f}" y2="{bottom + 34}" stroke="#dc2626" stroke-width="2" stroke-dasharray="7 5"/>'
    )
    lines.append(f'<text x="{endstep_x + 8:.1f}" y="{top + 18}" class="label" fill="#b91c1c">Endstep: 05.09</text>')

    pre_values = values[:20]
    post_values = values[20:]
    for label, avg, start, end, color in [
        ("до повышения", sum(pre_values) / len(pre_values), left, price_x, "#2563eb"),
        ("после повышения", sum(post_values) / len(post_values), price_x, width - right, "#c2410c"),
    ]:
        yy = y(avg)
        lines.append(
            f'<line x1="{start:.1f}" y1="{yy:.1f}" x2="{end:.1f}" y2="{yy:.1f}" stroke="{color}" stroke-width="2" stroke-dasharray="4 4"/>'
        )
        lines.append(
            f'<text x="{end - 4:.1f}" y="{yy - 8:.1f}" text-anchor="end" class="small" fill="{color}">{label}: {avg:.1f}</text>'
        )

    points = " ".join(f"{x(i):.1f},{y(value):.1f}" for i, value in enumerate(values))
    lines.append(f'<polyline points="{points}" fill="none" stroke="#2563eb" stroke-width="3"/>')
    for i, (row, value) in enumerate(zip(rows, values)):
        xx, yy = x(i), y(value)
        lines.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="5" fill="#1d4ed8"/>')
        lines.append(f'<text x="{xx:.1f}" y="{yy - 12:.1f}" text-anchor="middle" class="small">{value}</text>')
        lines.append(
            f'<text x="{xx:.1f}" y="{bottom + 24}" text-anchor="middle" class="small">{row["event_date"][5:].replace("-", ".")}</text>'
        )
    lines.append(
        f'<text x="{left}" y="{bottom + 58}" class="subtitle">Среднее до: 44,1 · после: 25,2 · изменение: −43%</text>'
    )
    return finish(lines)


def overlap_chart() -> str:
    width, height = 1050, 650
    left, top, bottom = 82, 105, 430
    plot_h = bottom - top
    bars = [
        ("Продолжили\nиграть в\n«Единороге»", 17, "#2563eb"),
        ("Кандидаты\nна\nпереключение", 11, "#f59e0b"),
        ("Не были в\n«Единороге»\nдо Endstep", 48, "#94a3b8"),
    ]
    max_value = 55
    bar_width, gap = 190, 85
    lines = svg_start(
        width,
        height,
        "Кто играет в обоих треках",
        "76 уникальных игроков обычного Endstep: временная проверка пересечения с понедельниками «Единорога».",
    )
    for tick in range(0, max_value + 1, 10):
        yy = bottom - tick / max_value * plot_h
        lines.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{width - 50}" y2="{yy:.1f}" class="grid"/>')
        lines.append(f'<text x="{left - 12}" y="{yy + 4:.1f}" text-anchor="end" class="small">{tick}</text>')
    lines.append(f'<line x1="{left}" y1="{bottom}" x2="{width - 50}" y2="{bottom}" class="axis"/>')
    lines.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" class="axis"/>')
    for i, (label, value, color) in enumerate(bars):
        bx = left + 55 + i * (bar_width + gap)
        bh = value / max_value * plot_h
        by = bottom - bh
        lines.append(f'<rect x="{bx}" y="{by:.1f}" width="{bar_width}" height="{bh:.1f}" rx="5" fill="{color}"/>')
        lines.append(
            f'<text x="{bx + bar_width / 2}" y="{by - 10:.1f}" text-anchor="middle" font-size="24" font-weight="700">{value}</text>'
        )
        for j, part in enumerate(label.split("\n")):
            lines.append(
                f'<text x="{bx + bar_width / 2}" y="{bottom + 28 + j * 17}" text-anchor="middle" class="small">{esc(part)}</text>'
            )
    lines += [
        '<rect x="82" y="535" width="886" height="70" rx="8" fill="#f8fafc" stroke="#dbe3ea"/>',
        '<text x="105" y="562" class="label">Основной ответ:</text>',
        '<text x="250" y="562" class="subtitle">28 из 76 (36,8%) когда-либо были в «Единороге».</text>',
        '<text x="105" y="588" class="subtitle">Чувствительность по заполненному городу не публикуется на уровне игроков.</text>',
    ]
    return finish(lines)


def candidate_chart(candidates: list[dict[str, str]]) -> str:
    candidates = sorted(candidates, key=lambda row: int(row["edinorog_before_count"]), reverse=True)
    width, height = 1350, 790
    left, top, bottom = 330, 120, 650
    plot_w, row_h = 560, 42
    max_value = 15
    lines = svg_start(
        width,
        height,
        "11 кандидатов на переход из «Единорога» в Endstep",
        "Слева — понедельники «Единорога» до первого Endstep; справа — дата первого Endstep и число Endstep-турниров.",
    )
    for tick in range(0, max_value + 1, 5):
        xx = left + tick / max_value * plot_w
        lines.append(f'<line x1="{xx:.1f}" y1="{top - 12}" x2="{xx:.1f}" y2="{bottom}" class="grid"/>')
        lines.append(f'<text x="{xx:.1f}" y="{bottom + 22}" text-anchor="middle" class="small">{tick}</text>')
    lines.append(f'<line x1="{left}" y1="{bottom}" x2="{left + plot_w}" y2="{bottom}" class="axis"/>')
    lines.append(f'<text x="{left}" y="{bottom + 48}" class="subtitle">Число понедельников до первого Endstep</text>')

    for index, row in enumerate(candidates):
        yy = top + index * row_h
        label = esc(row["player_id"])
        value = int(row["edinorog_before_count"])
        bar_w = value / max_value * plot_w
        lines.append(f'<text x="{left - 16}" y="{yy + 5}" text-anchor="end" class="label">{label}</text>')
        lines.append(f'<rect x="{left}" y="{yy - 14}" width="{bar_w:.1f}" height="25" rx="4" fill="#2563eb"/>')
        lines.append(f'<text x="{left + bar_w + 9:.1f}" y="{yy + 5}" class="label">{value}</text>')
        lines.append(
            f'<text x="{left + plot_w + 35}" y="{yy + 5}" class="small">первый Endstep: {row["first_endstep_date"][5:].replace("-", ".")} · турниров: {row["endstep_tournaments"]}</text>'
        )

    lines += [
        '<rect x="70" y="700" width="1210" height="55" rx="8" fill="#f8fafc" stroke="#dbe3ea"/>',
        '<text x="95" y="733" class="subtitle">Медиана: 3 понедельника · среднее: 5,5 · 6 из 11 играли не более 3 раз · 8 из 11 были только на одном Endstep.</text>',
    ]
    return finish(lines)


def club_attendance_chart(events: list[dict[str, str]], goldfish: list[dict[str, str]]) -> str:
    edinorog = [row for row in events if row["track"] == "edinorog_monday"]
    start_date = date.fromisoformat(edinorog[0]["event_date"])
    end_date = date.fromisoformat(edinorog[-1]["event_date"])
    width, height = 1400, 880
    left, right = 95, 55
    plot_w = width - left - right
    price_x = left + (PRICE_CHANGE_DATE - start_date).days / (end_date - start_date).days * plot_w
    endstep_x = left + (ENDSTEP_START_DATE - start_date).days / (end_date - start_date).days * plot_w

    def x(value: str) -> float:
        current = date.fromisoformat(value)
        return left + (current - start_date).days / (end_date - start_date).days * plot_w

    lines = svg_start(
        width,
        height,
        "Посещаемость «Единорога» и «Рыбы»",
        "Оранжевая линия — повышение цены 01.09; красная — первый Endstep 05.09. Серые точки «Рыбы» — записи с 0–1 участником.",
    )
    lines.append(f'<rect x="{price_x:.1f}" y="125" width="{width - right - price_x:.1f}" height="625" fill="#fff7ed"/>')
    lines.append(
        f'<line x1="{price_x:.1f}" y1="105" x2="{price_x:.1f}" y2="765" stroke="#ea580c" stroke-width="2" stroke-dasharray="5 5"/>'
    )
    lines.append(
        f'<text x="{price_x - 8:.1f}" y="98" text-anchor="end" class="label" fill="#c2410c">Цена: 01.09</text>'
    )
    lines.append(
        f'<line x1="{endstep_x:.1f}" y1="105" x2="{endstep_x:.1f}" y2="765" stroke="#dc2626" stroke-width="2" stroke-dasharray="7 5"/>'
    )
    lines.append(f'<text x="{endstep_x + 8:.1f}" y="122" class="label" fill="#b91c1c">Endstep: 05.09</text>')

    def panel(
        rows: list[dict[str, str]],
        panel_top: int,
        panel_bottom: int,
        max_value: int,
        title: str,
        color: str,
        low_points: bool = False,
    ) -> None:
        panel_height = panel_bottom - panel_top
        lines.append(f'<text x="{left}" y="{panel_top - 24}" class="label">{esc(title)}</text>')
        for tick in range(0, max_value + 1, 10):
            yy = panel_bottom - tick / max_value * panel_height
            lines.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{width - right}" y2="{yy:.1f}" class="grid"/>')
            lines.append(f'<text x="{left - 12}" y="{yy + 4:.1f}" text-anchor="end" class="small">{tick}</text>')
        lines.append(f'<line x1="{left}" y1="{panel_bottom}" x2="{width - right}" y2="{panel_bottom}" class="axis"/>')

        def y(value: int) -> float:
            return panel_bottom - value / max_value * panel_height

        points = " ".join(f"{x(row['event_date']):.1f},{y(int(row['participants'])):.1f}" for row in rows)
        lines.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" stroke-opacity="0.7"/>'
        )
        for row in rows:
            value = int(row["participants"])
            low = low_points and row.get("low_registration") == "true"
            point_color = "#94a3b8" if low else color
            fill = "#ffffff" if low else point_color
            lines.append(
                f'<circle cx="{x(row["event_date"]):.1f}" cy="{y(value):.1f}" r="5" fill="{fill}" stroke="{point_color}" stroke-width="2"/>'
            )

    panel(edinorog, 150, 400, 80, "Единорог · понедельники · 25 турниров", "#2563eb")
    panel(goldfish, 500, 750, 30, "Рыба · все записи Goldfish · 38 событий", "#059669", low_points=True)
    for tick in [
        date(2026, 4, 20),
        date(2026, 5, 1),
        date(2026, 6, 1),
        date(2026, 7, 1),
        date(2026, 8, 1),
        date(2026, 9, 1),
        date(2026, 10, 1),
    ]:
        if start_date <= tick <= end_date:
            lines.append(
                f'<text x="{left + (tick - start_date).days / (end_date - start_date).days * plot_w:.1f}" y="785" text-anchor="middle" class="small">{tick.strftime("%d.%m")}</text>'
            )
    lines += [
        '<rect x="95" y="815" width="1250" height="40" rx="7" fill="#f8fafc" stroke="#dbe3ea"/>',
        '<text x="115" y="841" class="subtitle">Единорог: 44,1 до цены → 25,2 после · Рыба: 8,0 до цены* → 19,4 после · *до цены 12 из 33 записей имели 0–1 участника.</text>',
    ]
    return finish(lines)


def candidate_club_chart(candidates: list[dict[str, str]], candidate_goldfish: list[dict[str, str]]) -> str:
    goldfish_by_id = {row["player_id"]: row for row in candidate_goldfish}
    candidates = sorted(candidates, key=lambda row: int(row["edinorog_before_count"]), reverse=True)
    width, height = 1400, 800
    left, top, bottom = 330, 120, 650
    plot_w, row_h, max_value = 560, 43, 15
    lines = svg_start(
        width,
        height,
        "11 кандидатов: «Единорог» и «Рыба» до первого Endstep",
        "Синие полосы — понедельники «Единорога»; зелёные — Goldfish до первого Endstep. Справа указано общее число Goldfish за весь период.",
    )
    for tick in range(0, max_value + 1, 5):
        xx = left + tick / max_value * plot_w
        lines.append(f'<line x1="{xx:.1f}" y1="{top - 12}" x2="{xx:.1f}" y2="{bottom}" class="grid"/>')
        lines.append(f'<text x="{xx:.1f}" y="{bottom + 22}" text-anchor="middle" class="small">{tick}</text>')
    lines.append(f'<line x1="{left}" y1="{bottom}" x2="{left + plot_w}" y2="{bottom}" class="axis"/>')
    lines.append(f'<text x="{left}" y="{bottom + 48}" class="subtitle">Число турниров до первого Endstep</text>')
    for index, row in enumerate(candidates):
        yy = top + index * row_h
        goldfish = goldfish_by_id[row["player_id"]]
        name = esc(row["player_id"])
        edinorog_value = int(row["edinorog_before_count"])
        goldfish_value = int(goldfish["goldfish_before_first_endstep"])
        lines.append(f'<text x="{left - 16}" y="{yy + 5}" text-anchor="end" class="label">{name}</text>')
        for offset, value, color in [(-10, edinorog_value, "#2563eb"), (6, goldfish_value, "#059669")]:
            bar_w = value / max_value * plot_w
            lines.append(f'<rect x="{left}" y="{yy + offset}" width="{bar_w:.1f}" height="11" rx="3" fill="{color}"/>')
            lines.append(f'<text x="{left + bar_w + 8:.1f}" y="{yy + offset + 9}" class="small">{value}</text>')
        lines.append(
            f'<text x="{left + plot_w + 35}" y="{yy + 5}" class="small">Goldfish всего: {goldfish["goldfish_total"]}</text>'
        )
    lines += [
        '<rect x="95" y="700" width="1245" height="55" rx="8" fill="#f8fafc" stroke="#dbe3ea"/>',
        '<rect x="120" y="721" width="18" height="10" rx="2" fill="#2563eb"/><text x="148" y="731" class="small">Единорог до Endstep</text>',
        '<rect x="310" y="721" width="18" height="10" rx="2" fill="#059669"/><text x="338" y="731" class="small">Рыба до Endstep</text>',
        '<text x="540" y="731" class="subtitle">В Рыбе были 4 из 11 кандидатов; всего 21 посещение, из них 18 до первого Endstep.</text>',
    ]
    return finish(lines)


def edinorog_goldfish_flow_chart(flow: list[dict[str, str]]) -> str:
    flow = sorted(flow, key=lambda row: (-int(row["edinorog_pre_count"]), row["player_id"]))
    width, height = 1450, 900
    left, top, bottom = 355, 125, 730
    plot_w, row_h, max_value = 570, 38, 16
    lines = svg_start(
        width,
        height,
        "Потенциальный переток: «Единорог» → «Рыба»",
        "19 игроков: были в понедельниках до 01.09, появились в Goldfish после 01.09 и не наблюдались в «Единороге» после повышения цены.",
    )
    for tick in range(0, max_value + 1, 4):
        xx = left + tick / max_value * plot_w
        lines.append(f'<line x1="{xx:.1f}" y1="{top - 12}" x2="{xx:.1f}" y2="{bottom}" class="grid"/>')
        lines.append(f'<text x="{xx:.1f}" y="{bottom + 22}" text-anchor="middle" class="small">{tick}</text>')
    lines.append(f'<line x1="{left}" y1="{bottom}" x2="{left + plot_w}" y2="{bottom}" class="axis"/>')
    lines.append(f'<text x="{left}" y="{bottom + 48}" class="subtitle">Число турниров до/после повышения цены</text>')
    for index, row in enumerate(flow):
        yy = top + index * row_h
        name = esc(row["player_id"])
        edinorog_value = int(row["edinorog_pre_count"])
        goldfish_value = int(row["goldfish_post_count"])
        lines.append(f'<text x="{left - 16}" y="{yy + 5}" text-anchor="end" class="label">{name}</text>')
        for offset, value, color in [(-10, edinorog_value, "#2563eb"), (6, goldfish_value, "#059669")]:
            bar_w = value / max_value * plot_w
            lines.append(f'<rect x="{left}" y="{yy + offset}" width="{bar_w:.1f}" height="11" rx="3" fill="{color}"/>')
            lines.append(f'<text x="{left + bar_w + 8:.1f}" y="{yy + offset + 9}" class="small">{value}</text>')
        lines.append(
            f'<text x="{left + plot_w + 35}" y="{yy + 5}" class="small">Goldfish всего: {row["goldfish_total"]}</text>'
        )
    lines += [
        '<rect x="95" y="785" width="1280" height="75" rx="8" fill="#f8fafc" stroke="#dbe3ea"/>',
        '<rect x="120" y="806" width="18" height="10" rx="2" fill="#2563eb"/><text x="148" y="816" class="small">«Единорог» до 01.09</text>',
        '<rect x="315" y="806" width="18" height="10" rx="2" fill="#059669"/><text x="343" y="816" class="small">Goldfish после 01.09</text>',
        '<text x="575" y="816" class="subtitle">37 игроков пришли из предшествующей аудитории «Рога» в Goldfish; 19 не вернулись в «Рог», 18 продолжили ходить.</text>',
        '<text x="120" y="842" class="subtitle">Доля потенциального перетока: 19 из 209 игроков «Рога» до повышения (9,1%).</text>',
    ]
    return finish(lines)


def main() -> None:
    CHARTS.mkdir(exist_ok=True)
    events = load_events()
    candidates = load_candidates()
    goldfish_events = load_goldfish_events()
    candidate_goldfish = load_candidate_goldfish()
    flow = load_edinorog_goldfish_flow()
    (CHARTS / "attendance_timeline.svg").write_text(attendance_chart(events), encoding="utf-8")
    (CHARTS / "audience_overlap.svg").write_text(overlap_chart(), encoding="utf-8")
    (CHARTS / "switch_candidates.svg").write_text(candidate_chart(candidates), encoding="utf-8")
    (CHARTS / "club_attendance_comparison.svg").write_text(
        club_attendance_chart(events, goldfish_events), encoding="utf-8"
    )
    (CHARTS / "candidate_club_comparison.svg").write_text(
        candidate_club_chart(candidates, candidate_goldfish), encoding="utf-8"
    )
    (CHARTS / "edinorog_goldfish_flow.svg").write_text(edinorog_goldfish_flow_chart(flow), encoding="utf-8")
    print(f"Generated {CHARTS / 'attendance_timeline.svg'}")
    print(f"Generated {CHARTS / 'audience_overlap.svg'}")
    print(f"Generated {CHARTS / 'switch_candidates.svg'}")
    print(f"Generated {CHARTS / 'club_attendance_comparison.svg'}")
    print(f"Generated {CHARTS / 'candidate_club_comparison.svg'}")
    print(f"Generated {CHARTS / 'edinorog_goldfish_flow.svg'}")


if __name__ == "__main__":
    main()
