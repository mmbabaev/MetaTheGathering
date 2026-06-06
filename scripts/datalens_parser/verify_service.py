"""Проверочный прогон сервиса DataLens.

Дёргает все три чарта для игрока, печатает таблицы и складывает результаты
(сырой ответ API + распарсенную сводку) в JSON-файлы в ~/Downloads.

    python3 scripts/datalens_parser/verify_service.py
    python3 scripts/datalens_parser/verify_service.py 'Фамилия Имя' --months 2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# репозиторий-рут в sys.path, чтобы импортировать services.*
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from services.datalens import (  # noqa: E402
    CHART_IDS,
    Chart,
    DataLensClient,
    DataLensService,
    Period,
    PlayerReport,
    _parse_row,
)

DOWNLOADS = Path.home() / "Downloads"

CHART_TITLES = {
    Chart.DECKS: ("Колоды игрока", "Колода"),
    Chart.OPPONENTS: ("Винрейт против оппонентов", "Оппонент"),
    Chart.OPPONENT_DECKS: ("Винрейт против дек оппонентов", "Колода оппонента"),
}


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text).strip("_")


def _print_table(title: str, name_col: str, rows: list) -> None:
    print(f"\n{title} — {len(rows)} строк")
    print(f"{name_col:<28}{'Матчей':>8}{'Винрейт':>10}")
    print("-" * 46)
    for row in rows:
        print(f"{row.name:<28}{row.matches:>8}{row.winrate:>9.1f}%")


def _run_scout(player: str, opponent: str) -> None:
    """Сценарий: колоды оппонента за 3 мес + мой винрейт против него за всё время."""
    service = DataLensService()
    scouting = service.scout_opponent(player, opponent)

    print(f"\nСкаутинг: {player}  vs  {opponent}")

    _print_table(
        f"Колоды оппонента ({opponent}) за 3 месяца",
        "Колода",
        scouting.opponent_decks,
    )

    h2h = scouting.head_to_head
    print(f"\nМой винрейт против {opponent} (за всё время):")
    if h2h:
        print(f"  {h2h.matches} матч(ей), винрейт {h2h.winrate:.1f}%")
    else:
        print("  матчей не найдено")

    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    out = DOWNLOADS / f"datalens_scout_{_slug(player)}_vs_{_slug(opponent)}.json"
    out.write_text(scouting.model_dump_json(indent=2))
    print(f"\nСохранено в ~/Downloads:\n  {out.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка services.datalens")
    parser.add_argument("player", nargs="?", default="Бабаев Михаил", help="Фамилия Имя")
    parser.add_argument("--months", type=int, default=None, help="период: последние N месяцев")
    parser.add_argument("--scout", metavar="ОППОНЕНТ", default=None, help="скаутинг: колоды оппонента + мой H2H")
    args = parser.parse_args()

    if args.scout:
        _run_scout(args.player, args.scout)
        return

    period = Period.last_months(args.months) if args.months else Period.all_time()
    period_label = f"{args.months}мес" if args.months else "all-time"

    client = DataLensClient()
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    player_slug = _slug(args.player)
    saved: list[Path] = []
    report = PlayerReport(player=args.player, period=period.raw)

    for chart in Chart:
        title, name_col = CHART_TITLES[chart]
        raw = client.run(
            CHART_IDS[chart],
            {
                "klub_77wt": "",
                "data_v9da": period.raw,
                "igrok_4vy1": args.player,
                "uchastnik_0zyi": args.player,
            },
        )
        # сырой ответ дашборда → ~/Downloads
        raw_path = DOWNLOADS / f"datalens_{chart.value}_{player_slug}_{period_label}.json"
        raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2))
        saved.append(raw_path)

        rows = [_parse_row(row) for row in raw.get("data", {}).get("rows", [])]
        setattr(report, chart.value, rows)
        _print_table(title, name_col, rows)

    # распарсенная сводка целиком
    report_path = DOWNLOADS / f"datalens_report_{player_slug}_{period_label}.json"
    report_path.write_text(report.model_dump_json(indent=2))
    saved.append(report_path)

    print(f"\nИгрок: {args.player} | период: {period_label}")
    print("Сохранено в ~/Downloads:")
    for path in saved:
        print(f"  {path.name}")


if __name__ == "__main__":
    main()
