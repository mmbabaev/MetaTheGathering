"""Разовая проверка порядка столов в турнирах формата «единорог».

Качает указанные турниры AetherHub через прод-парсер (AetherhubService),
печатает столы последнего раунда и проверяет, что номера столов идут подряд
1..N и каждый стол встречается ровно для двух игроков (обе стороны паринга).

Запуск:
    python3 scripts/check_edinorog_tables.py 100007 99893
    python3 scripts/check_edinorog_tables.py            # дефолтный набор
"""

import sys
from collections import Counter

from services.aetherhub_service import AetherhubService

DEFAULT_IDS = ["100007", "99893", "99992"]
URL = "https://aetherhub.com/Tourney/RoundTourney/{}"


def check(tourney_id: str) -> bool:
    data = AetherhubService().fetch_tournament(URL.format(tourney_id))
    if not data.rounds:
        print(f"#{tourney_id}: раундов нет (вероятно, js-формат / турнир не завершён)")
        return False

    last = data.rounds[-1]
    pairings = last.pairings
    tables = [p.table_number for p in pairings]
    missing = sum(1 for t in tables if t is None)
    present = sorted({t for t in tables if t is not None})

    print(f"\n#{tourney_id} — раунд {last.number}: {len(pairings)} строк парингов")
    print(f"  столов уникальных: {len(present)} | без номера стола: {missing}")
    if present:
        print(f"  диапазон столов: {present[0]}..{present[-1]}")
        contiguous = present == list(range(present[0], present[-1] + 1))
        print(f"  столы идут подряд (1..N без дыр): {contiguous}")
        # каждый стол — 2 строки (обе стороны паринга); 1 строка = бай (нечётно игроков)
        counts = Counter(t for t in tables if t is not None)
        byes = sorted(t for t, c in counts.items() if c == 1)
        broken = {t: c for t, c in counts.items() if c not in (1, 2)}
        print(f"  баи (стол с 1 игроком): {byes or 'нет'}")
        print(f"  битые столы (не 1 и не 2 игрока): {broken or 'нет'}")
        print("  первые столы по порядку:")
        for p in sorted(pairings, key=lambda x: (x.table_number or 10**9, x.player))[:8]:
            print(f"    стол {p.table_number}: {p.player} vs {p.opponent} [{p.player_wins}-{p.opponent_wins}]")
        return contiguous and not broken and missing == 0
    return False


def main() -> None:
    ids = sys.argv[1:] or DEFAULT_IDS
    results = {tid: check(tid) for tid in ids}
    print("\n=== ИТОГ ===")
    for tid, ok in results.items():
        print(f"  #{tid}: {'OK — столы по порядку, по 2 игрока' if ok else 'ПРОВЕРЬ вручную'}")


if __name__ == "__main__":
    main()
