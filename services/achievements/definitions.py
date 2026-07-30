"""Реестр ачивок — единственный источник правды об их названиях, уровнях и порогах.

Определения живут в коде (как ``KNOWN_FLAGS`` у feature flags): их не редактируют из UI,
они версионируются вместе с логикой правил. Порядок в ``ACHIEVEMENTS`` — порядок показа
в UI и в отчёте.

См. docs/achievements.md §3, §5.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class Codes:
    """Коды ачивок. Строкой пользуемся только здесь и в тестах."""

    DEBUT = "debut"
    UNDEFEATED = "undefeated"
    SCRIBE = "scribe"
    REGULAR = "regular"
    MULTICLASS = "multiclass"
    FIRST_DECK = "first_deck"
    LOYALIST = "loyalist"


class Rarity:
    COMMON = "common"
    RARE = "rare"
    EPIC = "epic"


@dataclass(frozen=True)
class AchievementDef:
    """Одно определение = один код + уровень."""

    code: str
    level: int
    title: str  # «Мультикласс»
    icon: str  # «🎭» — текстовый UI; в картинках эмодзи не используем (в DejaVu их нет)
    description: str  # что это значит
    hint: str  # что сделать, чтобы открыть
    rarity: str
    threshold: Optional[int] = None  # порог счётчика; None — одноразовая ачивка без прогресса

    @property
    def key(self) -> tuple[str, int]:
        return self.code, self.level

    @property
    def title_with_level(self) -> str:
        """«Без поражений II» — римская цифра только у многоуровневых."""
        if self.threshold is None:
            return self.title
        return f"{self.title} {_ROMAN.get(self.level, self.level)}"


_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV"}


_DEFS: list[AchievementDef] = [
    AchievementDef(
        code=Codes.DEBUT,
        level=1,
        title="Дебют",
        icon="🎖",
        description="Записал свою первую колоду",
        hint="Запиши свою колоду на турнир самостоятельно",
        rarity=Rarity.COMMON,
    ),
    *(
        AchievementDef(
            code=Codes.UNDEFEATED,
            level=level,
            title="Без поражений",
            icon="🏆",
            description=description,
            hint="Пройди турнир без поражений и ничьих",
            rarity=rarity,
            threshold=threshold,
        )
        for level, threshold, rarity, description in (
            (1, 1, Rarity.RARE, "Прошёл турнир без единого поражения"),
            (2, 3, Rarity.RARE, "Три турнира без единого поражения"),
            (3, 10, Rarity.EPIC, "Десять турниров без единого поражения"),
        )
    ),
    *(
        AchievementDef(
            code=Codes.SCRIBE,
            level=level,
            title="Метаписец",
            icon="🧙",
            description=description,
            hint="Записывай колоды других игроков — кнопка «Записать оппонентов»",
            rarity=rarity,
            threshold=threshold,
        )
        for level, threshold, rarity, description in (
            (1, 3, Rarity.COMMON, "Записал три чужие колоды"),
            (2, 10, Rarity.COMMON, "Записал десять чужих колод"),
            (3, 25, Rarity.RARE, "Записал двадцать пять чужих колод"),
            (4, 50, Rarity.EPIC, "Записал полсотни чужих колод"),
        )
    ),
    *(
        AchievementDef(
            code=Codes.REGULAR,
            level=level,
            title="Завсегдатай",
            icon="📅",
            description=description,
            hint="Приходи на турниры клуба без пропусков и записывай колоду сам",
            rarity=rarity,
            threshold=threshold,
        )
        for level, threshold, rarity, description in (
            (1, 4, Rarity.COMMON, "Четыре турнира клуба подряд"),
            (2, 8, Rarity.RARE, "Восемь турниров клуба подряд"),
            (3, 16, Rarity.EPIC, "Шестнадцать турниров клуба подряд"),
        )
    ),
    *(
        AchievementDef(
            code=Codes.MULTICLASS,
            level=level,
            title="Мультикласс",
            icon="🎭",
            description=description,
            hint="Пробуй разные архетипы — считаются последние 90 дней",
            rarity=rarity,
            threshold=threshold,
        )
        for level, threshold, rarity, description in (
            (1, 3, Rarity.COMMON, "Три разные колоды за 90 дней"),
            (2, 5, Rarity.RARE, "Пять разных колод за 90 дней"),
            (3, 8, Rarity.EPIC, "Восемь разных колод за 90 дней"),
        )
    ),
    *(
        AchievementDef(
            code=Codes.FIRST_DECK,
            level=level,
            title="Буду первый",
            icon="⚡",
            description=description,
            hint="Запиши свою колоду первым — быстрее остальных участников",
            rarity=rarity,
            threshold=threshold,
        )
        for level, threshold, rarity, description in (
            (1, 1, Rarity.COMMON, "Записал колоду раньше всех на турнире"),
            (2, 3, Rarity.RARE, "Трижды записал колоду раньше всех"),
            (3, 10, Rarity.EPIC, "Десять раз записал колоду раньше всех"),
        )
    ),
    *(
        AchievementDef(
            code=Codes.LOYALIST,
            level=level,
            title="Однолюб",
            icon="💍",
            description=description,
            hint="Не меняй архетип от турнира к турниру",
            rarity=rarity,
            threshold=threshold,
        )
        for level, threshold, rarity, description in (
            (1, 3, Rarity.COMMON, "Три турнира подряд на одной колоде"),
            (2, 5, Rarity.RARE, "Пять турниров подряд на одной колоде"),
            (3, 10, Rarity.EPIC, "Десять турниров подряд на одной колоде"),
        )
    ),
]

ACHIEVEMENTS: dict[tuple[str, int], AchievementDef] = {d.key: d for d in _DEFS}

# Порядок кодов для UI и отчёта.
CODE_ORDER: list[str] = [
    Codes.DEBUT,
    Codes.FIRST_DECK,
    Codes.UNDEFEATED,
    Codes.SCRIBE,
    Codes.REGULAR,
    Codes.MULTICLASS,
    Codes.LOYALIST,
]


def get(code: str, level: int) -> Optional[AchievementDef]:
    return ACHIEVEMENTS.get((code, level))


def levels_for(code: str) -> list[AchievementDef]:
    """Все уровни одного кода по возрастанию."""
    return sorted((d for d in ACHIEVEMENTS.values() if d.code == code), key=lambda d: d.level)


def next_level_for(code: str, value: int) -> Optional[AchievementDef]:
    """Первый уровень, порог которого ещё не взят значением ``value``.

    None — все уровни этого кода уже покрыты (или ачивка одноразовая).
    """
    for definition in levels_for(code):
        if definition.threshold is not None and value < definition.threshold:
            return definition
    return None


def reached_levels(code: str, value: int) -> list[AchievementDef]:
    """Уровни, чьи пороги взяты значением ``value``."""
    return [d for d in levels_for(code) if d.threshold is not None and value >= d.threshold]
