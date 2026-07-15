"""Справочник known-колод Pauper: как называть на графике и какого они цвета.

Составлен вручную по 15 последним турнирам клубов (145 архетипов, 514 колод) — цвета
подтверждены игроком, а не выведены из названия. Словарь **сильнее** и эвристики, и кэша
в БД: это источник истины, правка здесь применяется сразу.

Две задачи:
- **цвет** — там, где из названия его не вывести («Spy Walls», «Ponza»);
- **группировка** — несколько названий сводятся в одну строку легенды и один сектор
  («Spy Walls» + «Spy» + «Spy Combo» → «Spy Combo»; все троны → «Tron»).

Ключи нормализованные (см. `normalize_deck_name`), поэтому регистр, дефисы и эмодзи
в названии значения не имеют: «Flicker tron», «Flicker Tron» и «🔵 Flicker-Tron» — одна запись.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Эмодзи и прочие пиктограммы: игроки метят ими колоду («🟢🔵🐸 Bogles»).
# Для сравнения имён они шум, а в легенде — квадраты-тофу: в DejaVu таких глифов нет.
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


# Цвета в словаре пишутся руками, поэтому опечатку («GB» вместо «BG» не страшно — canon
# разберётся, а вот «GX» или «Bg» — уже мусор) стережёт тест через эту проверку.
WUBRG_OK = re.compile(r"[WUBRG]*")


@dataclass(frozen=True)
class KnownDeck:
    """Как показать колоду в легенде и какого она цвета."""

    display: str  # каноничное название; общее у всех имён одной группы
    colors: str  # подмножество WUBRG, "" = бесцветная


def strip_pictographs(name: str) -> str:
    """Название без эмодзи и лишних пробелов. Пустой результат — возвращаем исходное."""
    cleaned = re.sub(r"\s+", " ", _PICTOGRAPHS_RE.sub("", name)).strip()
    return cleaned or name.strip()


def normalize_deck_name(name: str) -> str:
    """Ключ для сравнения названий: без эмодзи, регистра, дефисов и лишних пробелов.

    «Caw-Gates», «Caw Gates» и «caw gates» — одна колода; в проде такие варианты
    лежат отдельными архетипами и без нормализации дробили бы график.
    """
    cleaned = strip_pictographs(name).lower().replace("-", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", cleaned, flags=re.UNICODE)).strip()


def _book(*entries: tuple[str, str, tuple[str, ...]]) -> dict[str, KnownDeck]:
    """Собирает словарь: (каноничное имя, цвета, синонимы) → записи по нормализованным ключам."""
    result: dict[str, KnownDeck] = {}
    for display, colors, aliases in entries:
        deck = KnownDeck(display=display, colors=colors)
        for alias in (display, *aliases):
            result[normalize_deck_name(alias)] = deck
    return result


# (каноничное имя, цвета, синонимы-и-члены-группы)
DECK_BOOK = _book(
    # --- группы: несколько названий → одна строка легенды ---
    # Spy Walls / Spy / Spy Combo — одна колода, названная по-разному.
    ("Spy Combo", "BG", ("Spy", "Spy Walls")),
    # Все троны в одну группу. Цвет — бесцветный: у объединённой группы единого цвета нет,
    # а Tron — та самая артефактная колода (в сиде помечен ⚙️).
    ("Tron", "", ("Flicker Tron", "Monster Tron", "Altar Tron")),
    ("Bogles", "GW", ("Boggles",)),
    ("Pizza", "BG", ("Pizza Combo", "Pizza Affinity")),
    ("Inside Out", "UR", ()),
    ("Ninja Rats", "UB", ()),
    # --- цвет, который из названия не вывести ---
    ("Elves", "G", ()),
    ("Poison Storm", "UG", ()),
    ("Cycle Storm", "RG", ()),
    ("Ruby Storm", "R", ()),
    ("Caw-Gates", "WU", ("Caw Gates",)),
    ("Gates", "WUG", ()),
    ("Rogue", "UB", ()),
    ("Gardens", "BG", ()),
    ("Turbo Fog", "WUG", ()),
    ("Ponza", "RG", ()),
    ("Food Pestilence", "BG", ()),
    ("Tortured Existence", "B", ()),
    ("Walls", "G", ()),
    ("Slivers", "WUBRG", ()),
    ("Familiars", "WU", ()),
    ("Infect", "UG", ()),
    ("Mono Madness", "R", ()),
    ("Mono Faeries", "U", ()),
)


def lookup_deck(name: str) -> Optional[KnownDeck]:
    """Запись справочника по названию архетипа. None — колоды в справочнике нет."""
    return DECK_BOOK.get(normalize_deck_name(name))
