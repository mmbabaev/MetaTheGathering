"""Цветовая идентичность колоды по названию архетипа + палитра для графика.

Списка карт у нас нет — храним только название архетипа, поэтому цвет определяем из имени:
1. эвристический парсер (гильдии/шарды/клинья, инициалы вроде «UW», цветовые слова, артефактные маркеры);
2. LLM-фолбэк для флейворных имён («Spy Combo»), если он сконфигурирован;
3. дефолт — бесцветная.

Результат кэшируется в `Archetype.color_identity` — LLM дёргается максимум раз на архетип.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from core import models
from services.llm import YandexLLM

logger = logging.getLogger(__name__)

WUBRG = "WUBRG"
COLORLESS = ""  # бесцветная колода; NULL в БД означает «ещё не определяли»

_GUILDS = {
    "azorius": "WU",
    "dimir": "UB",
    "rakdos": "BR",
    "gruul": "RG",
    "selesnya": "GW",
    "orzhov": "WB",
    "izzet": "UR",
    "golgari": "BG",
    "boros": "RW",
    "simic": "GU",
}

_SHARDS_WEDGES = {
    "esper": "WUB",
    "grixis": "UBR",
    "jund": "BRG",
    "naya": "RGW",
    "bant": "GWU",
    "abzan": "WBG",
    "jeskai": "URW",
    "sultai": "BGU",
    "mardu": "RWB",
    "temur": "GUR",
}

_FOUR_COLOR = {
    "yore-tiller": "WUBR",
    "glint-eye": "UBRG",
    "dune-brood": "BRGW",
    "ink-treader": "RGWU",
    "witch-maw": "GWUB",
}

# Однословные маркеры пяти цветов.
_FIVE_COLOR = {"wubrg": "WUBRG", "5c": "WUBRG", "domain": "WUBRG"}

_NAMED = {**_GUILDS, **_SHARDS_WEDGES, **_FOUR_COLOR, **_FIVE_COLOR}

# Многословные маркеры — ищем как подстроку в нормализованном имени.
_NAMED_PHRASES = {"five color": "WUBRG", "5 color": "WUBRG"}

_COLOR_WORDS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}

_COLORLESS_WORDS = {"affinity", "tron", "artifact", "artifacts", "colorless", "eldrazi"}

# Цвет сектора по цветовой идентичности. Моно — канонические цвета MTG,
# многоцветные — смесь в духе своих цветов, бесцветные — серый.
# Ключи записаны в привычном для MTG порядке («RW» = Boros) и канонизируются ниже,
# поэтому порядок букв здесь не важен — важна полнота (все 32 подмножества WUBRG).
_PALETTE_RAW = {
    "": "#9AA3AD",
    "W": "#F2ECD5",
    "U": "#3B7DD8",
    "B": "#4A4458",
    "R": "#D4453C",
    "G": "#3FA35F",
    # гильдии
    "WU": "#A8C4E5",
    "UB": "#3E5570",
    "BR": "#8C3A3A",
    "RG": "#D97A2B",
    "GW": "#9CC46B",
    "WB": "#8B8698",
    "UR": "#7B5EA7",
    "BG": "#5A6B45",
    "RW": "#F0A868",
    "GU": "#4FB89A",
    # шарды и клинья
    "WUB": "#6E7C99",
    "UBR": "#6B5A78",
    "BRG": "#7A3B2E",
    "RGW": "#C98A4B",
    "GWU": "#7FB3A8",
    "WBG": "#7D8A6A",
    "URW": "#B07FA8",
    "BGU": "#4A6B63",
    "RWB": "#A85A50",
    "GUR": "#5FAF96",
    # четыре цвета
    "WUBR": "#B08A6E",
    "WUBG": "#8FA07E",
    "WURG": "#A9A05E",
    "WBRG": "#B58A4E",
    "UBRG": "#8C7A5A",
    # все пять
    "WUBRG": "#D4AF37",
}

_LLM_SYSTEM = (
    "Ты эксперт по формату Magic: The Gathering Pauper. "
    "По названию архетипа колоды определи её цветовую идентичность. "
    'Ответь строго JSON вида {"colors":"UB"}, где colors — подмножество букв WUBRG '
    '(W=белый, U=синий, B=чёрный, R=красный, G=зелёный) или "C" для бесцветной колоды. '
    "Никакого текста кроме JSON."
)


def canon(colors: str) -> str:
    """Приводит набор цветов к канону: порядок WUBRG, без повторов, только буквы цветов."""
    present = {c for c in colors.upper() if c in WUBRG}
    return "".join(c for c in WUBRG if c in present)


PALETTE = {canon(key): value for key, value in _PALETTE_RAW.items()}


def hex_for(color_identity: Optional[str]) -> str:
    """Hex-цвет сектора. Неизвестная идентичность → серый (график не должен падать)."""
    return PALETTE.get(canon(color_identity or ""), PALETTE[COLORLESS])


def _words(name: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", name)


def _named_combo(lowered: list[str]) -> Optional[str]:
    for word in lowered:
        if word in _NAMED:
            return canon(_NAMED[word])
    text = " ".join(lowered)
    for phrase, colors in _NAMED_PHRASES.items():
        if phrase in text:
            return canon(colors)
    return None


def _initials(words: list[str]) -> Optional[str]:
    """Токены-инициалы: «UW Familiars», «RG Storm», «WW».

    Требуем верхний регистр — иначе обычные слова из букв WUBRG («grub») ложно
    распознаются как цвета.
    """
    for word in words:
        if 2 <= len(word) <= 5 and word.isupper() and all(c in WUBRG for c in word):
            return canon(word)
    return None


def _from_color_words(lowered: list[str]) -> Optional[str]:
    found = "".join(_COLOR_WORDS[w] for w in lowered if w in _COLOR_WORDS)
    return canon(found) if found else None


def parse_color_identity(name: str) -> Optional[str]:
    """Цветовая идентичность из названия архетипа. None — эвристика не разобрала.

    Порядок важен: «Grixis Affinity» — это UBR, а не бесцветная.
    """
    words = _words(name)
    lowered = [w.lower() for w in words]

    named = _named_combo(lowered)
    if named is not None:
        return named

    initials = _initials(words)
    if initials is not None:
        return initials

    from_words = _from_color_words(lowered)
    if from_words is not None:
        return from_words

    if any(word in _COLORLESS_WORDS for word in lowered):
        return COLORLESS

    return None


class DeckColorResolver:
    """Определяет и кэширует цветовую идентичность архетипов."""

    def __init__(self, db: Session, llm: Optional[YandexLLM] = None):
        self.db = db
        self.llm = llm if llm is not None else YandexLLM()

    def resolve(self, archetype: models.Archetype) -> str:
        """Цветовая идентичность архетипа. Кэширует определённое значение в БД.

        Дефолт (ничего не определилось) НЕ кэшируем: оставляем NULL, чтобы архетип
        переопределился, когда появится LLM или ручной оверрайд.
        """
        if archetype.color_identity is not None:
            return canon(archetype.color_identity)

        colors = parse_color_identity(archetype.name)
        if colors is None:
            colors = self._ask_llm(archetype.name)
        if colors is None:
            return COLORLESS

        archetype.color_identity = colors
        self.db.commit()
        return colors

    def resolve_many(self, archetypes: Iterable[models.Archetype]) -> dict[int, str]:
        """Цвета для набора архетипов: {archetype_id: color_identity}."""
        return {a.id: self.resolve(a) for a in archetypes}

    def _ask_llm(self, name: str) -> Optional[str]:
        if not self.llm.enabled:
            return None
        answer = self.llm.complete(_LLM_SYSTEM, name)
        if not answer:
            return None
        return self._parse_llm_answer(answer, name)

    @staticmethod
    def _parse_llm_answer(answer: str, name: str) -> Optional[str]:
        match = re.search(r"\{.*\}", answer, re.DOTALL)
        if not match:
            logger.warning("[deck_colors] LLM вернула не-JSON для %r: %r", name, answer)
            return None
        try:
            colors = json.loads(match.group(0)).get("colors", "")
        except (ValueError, AttributeError):
            logger.warning("[deck_colors] LLM вернула битый JSON для %r: %r", name, answer)
            return None
        if isinstance(colors, str) and colors.strip().upper() == "C":
            return COLORLESS
        return canon(colors) if isinstance(colors, str) else None
