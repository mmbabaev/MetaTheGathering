"""Ачивки «сыграл на такой-то колоде» — по топ-колодам меты.

Имя колоды игрок пишет как хочет («Dimir Terror», «Blue Delver», «UB terror»), поэтому
сопоставляем не строку, а **общий тип** из ``services.deck_mapping.general_archetype``
(тот же, по которому схлопывается график меты). Дополнительно ловим подстроки — для
семейств, где общих типов много: любой Tron, любой Affinity, любые Faeries.

Названия нарочно сленговые: это фан-ачивки, они должны читаться как прозвища из чата,
а не как строки из справочника.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from services.deck_mapping import general_archetype


@dataclass(frozen=True)
class DeckAchievement:
    """Одна деко-ачивка: как называется и по каким колодам засчитывается."""

    code: str  # "deck_terror" — идёт в UserAchievement.code
    title: str
    icon: str
    description: str
    general_names: frozenset[str] = field(default_factory=frozenset)  # точное совпадение общего типа
    substrings: tuple[str, ...] = ()  # подстрока в нормализованном названии (семейства колод)


DECK_ACHIEVEMENTS: list[DeckAchievement] = [
    DeckAchievement(
        code="deck_terror",
        title="УЖ",
        icon="🐍",
        description="Сыграл на Terror (Blue / UB)",
        general_names=frozenset({"Blue Terror", "UB Terror"}),
    ),
    DeckAchievement(
        code="deck_madness",
        title="Crazy",
        icon="🤪",
        description="Сыграл на Madness (Red / BR)",
        general_names=frozenset({"Red Madness", "BR Madness"}),
    ),
    DeckAchievement(
        code="deck_tron",
        title="Царь",
        icon="👑",
        description="Сыграл на Tron — любом из них",
        substrings=("tron",),
    ),
    DeckAchievement(
        code="deck_affinity",
        title="Железяка",
        icon="⚙️",
        description="Сыграл на Affinity",
        substrings=("affinity",),
    ),
    DeckAchievement(
        code="deck_elves",
        title="Лесник",
        icon="🌿",
        description="Сыграл на Elves",
        general_names=frozenset({"Elves"}),
    ),
    DeckAchievement(
        code="deck_burn",
        title="Пиромант",
        icon="🔥",
        description="Сыграл на Burn",
        general_names=frozenset({"Burn"}),
    ),
    DeckAchievement(
        code="deck_spy",
        title="Шпион",
        icon="🕵️",
        description="Сыграл на Spy / Walls Combo",
        general_names=frozenset({"Spy Walls"}),
        substrings=("spy combo",),
    ),
    DeckAchievement(
        code="deck_white_aggro",
        title="Крестоносец",
        icon="⚔️",
        description="Сыграл на White Aggro",
        general_names=frozenset({"White Aggro"}),
    ),
    DeckAchievement(
        code="deck_gates",
        title="Вратарь",
        icon="🚪",
        description="Сыграл на Gates",
        substrings=("gates",),
    ),
    DeckAchievement(
        code="deck_faeries",
        title="Крылья",
        icon="🧚",
        description="Сыграл на Faeries",
        substrings=("faeries", "феи"),
    ),
    DeckAchievement(
        code="deck_familiars",
        title="Фамильяр",
        icon="🦉",
        description="Сыграл на Familiars",
        substrings=("familiars", "fams"),
    ),
    DeckAchievement(
        code="deck_blade",
        title="Клинок",
        icon="🗡",
        description="Сыграл на Blade",
        substrings=("blade",),
    ),
    DeckAchievement(
        code="deck_wildfire",
        title="Поджигатель",
        icon="🌋",
        description="Сыграл на Jund Midrange / Wildfire",
        general_names=frozenset({"Jund Midrange"}),
        substrings=("wildfire",),
    ),
    DeckAchievement(
        code="deck_sacrifice",
        title="Жнец",
        icon="💀",
        description="Сыграл на Sacrifice",
        substrings=("sacrifice",),
    ),
    DeckAchievement(
        code="deck_ramp",
        title="Лесоруб",
        icon="🪓",
        description="Сыграл на Ponza / RG Ramp",
        general_names=frozenset({"RG Ramp"}),
        substrings=("ponza",),
    ),
]

DECK_BY_CODE = {d.code: d for d in DECK_ACHIEVEMENTS}


def deck_codes_for(name: Optional[str], general_name: Optional[str] = None) -> list[str]:
    """Коды деко-ачивок, которые засчитывает эта колода. Обычно ноль или один.

    Сначала пробуем точное совпадение общего типа (``general_name`` из БД либо считаем на
    лету), затем — подстроки в исходном названии: игрок мог написать «Uw fams», для которого
    общий тип известен, и «Kuldotha Tron», для которого нет.
    """
    if not name and not general_name:
        return []
    general = general_name or (general_archetype(name) if name else None)
    haystack = " ".join(part for part in (name, general) if part).lower()

    codes = []
    for achievement in DECK_ACHIEVEMENTS:
        if general and general in achievement.general_names:
            codes.append(achievement.code)
            continue
        if any(sub in haystack for sub in achievement.substrings):
            codes.append(achievement.code)
    return codes
