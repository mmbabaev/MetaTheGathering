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
from services.deck_book import lookup_deck
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

# Однословные маркеры пяти цветов.
_FIVE_COLOR = {"wubrg": "WUBRG", "5c": "WUBRG", "domain": "WUBRG"}

_NAMED = {**_GUILDS, **_SHARDS_WEDGES, **_FIVE_COLOR}

# Многословные маркеры — ищем как подстроку в имени, разобранном на слова.
# Четырёхцветные имена пишут через дефис («Yore-Tiller»), но токенизатор дефис срезает,
# поэтому они живут здесь, а не в _NAMED — как двусловные фразы.
_NAMED_PHRASES = {
    "five color": "WUBRG",
    "5 color": "WUBRG",
    "yore tiller": "WUBR",
    "glint eye": "UBRG",
    "dune brood": "BRGW",
    "ink treader": "RGWU",
    "witch maw": "GWUB",
}

_COLOR_WORDS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}

# Игроки часто сами помечают цвет колоды эмодзи: «🟢🔵🐸 Bogles», «Bg pestilence ⚫️🟢🌱💀».
# Только однозначные цвета: 🟤/⚙️ и прочий флейвор игнорируем.
_COLOR_EMOJI = {
    "⚪": "W",
    "⬜": "W",
    "🤍": "W",
    "🔵": "U",
    "🟦": "U",
    "💙": "U",
    "⚫": "B",
    "⬛": "B",
    "🖤": "B",
    "🔴": "R",
    "🟥": "R",
    "❤": "R",
    "🟢": "G",
    "🟩": "G",
    "💚": "G",
}

# Слов-маркеров «бесцветности» (affinity/tron/artifact) здесь намеренно нет.
# Они врут: «Flicker Tron» — синяя колода, «Grixis Affinity» — UBR, а голая «Affinity»
# в Pauper обычно BR. Раньше такой маркер отдавал COLORLESS, resolve() кэшировал его
# навсегда и до LLM дело уже не доходило. Теперь такие имена возвращают None и уходят
# в LLM; без LLM они и так рисуются серыми — но серое не кэшируется и переопределится.

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


def _is_initials_token(word: str, has_mono: bool) -> bool:
    """Похож ли токен на инициалы цветов.

    Регистр — единственный способ отличить инициалы от обычного слова из тех же букв:
    - ВЕРХНИЙ регистр, 2–5 букв: «UW», «RG», «BUG», «WW»;
    - Заглавная, 2–3 буквы: «Ub Faerie», «Bg pestilence» — так пишут в реальных названиях.
      Ограничение по длине отсекает слова вроде «Grub»;
    - одна буква — только рядом со словом «mono»: «Mono U faeries».
    """
    if not all(c in WUBRG for c in word.upper()):
        return False
    if len(word) == 1:
        return has_mono and word.isupper()
    if word.isupper():
        return len(word) <= 5
    return len(word) <= 3 and word[0].isupper()


def _initials(words: list[str]) -> Optional[str]:
    """Токены-инициалы: «UW Familiars», «RG Storm», «Ub Faerie», «Mono U faeries»."""
    has_mono = any(w.lower() == "mono" for w in words)
    for word in words:
        if _is_initials_token(word, has_mono):
            return canon(word)
    return None


def _from_color_emoji(name: str) -> Optional[str]:
    found = "".join(_COLOR_EMOJI[ch] for ch in name if ch in _COLOR_EMOJI)
    return canon(found) if found else None


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

    from_emoji = _from_color_emoji(name)
    if from_emoji is not None:
        return from_emoji

    return _from_color_words(lowered)


class DeckColorResolver:
    """Определяет и кэширует цветовую идентичность архетипов."""

    def __init__(self, db: Session, llm: Optional[YandexLLM] = None):
        self.db = db
        self.llm = llm if llm is not None else YandexLLM()

    def resolve(self, archetype: models.Archetype) -> str:
        """Цветовая идентичность архетипа. Кэширует определённое значение в БД."""
        colors = self._resolve_uncommitted(archetype)
        if archetype.color_identity is not None:
            self.db.commit()
        return colors

    def resolve_many(self, archetypes: Iterable[models.Archetype]) -> dict[int, str]:
        """Цвета для набора архетипов: {archetype_id: color_identity}.

        Коммитим один раз в конце, а не на каждый архетип: иначе один график —
        это N транзакций, каждая из которых заодно фиксирует чужие несохранённые
        изменения в той же сессии.
        """
        result = {a.id: self._resolve_uncommitted(a) for a in archetypes}
        self.db.commit()
        return result

    def _resolve_uncommitted(self, archetype: models.Archetype) -> str:
        """Определяет цвет и пишет его в объект, но не коммитит.

        Дефолт (ничего не определилось) НЕ проставляем: оставляем NULL, чтобы архетип
        переопределился, когда появится LLM или ручной оверрайд.
        """
        # Справочник сильнее кэша: он источник истины, и правка в коде должна применяться
        # сразу, а не ждать, пока протухнет color_identity в БД. Кэшировать его незачем.
        known = lookup_deck(archetype.name)
        if known is not None:
            return canon(known.colors)

        if archetype.color_identity is not None:
            return canon(archetype.color_identity)

        colors = parse_color_identity(archetype.name)
        if colors is None:
            # Сигнал слабее имени («Grixis Affinity» помечен ⚙️, хотя это UBR),
            # поэтому только когда имя не разобралось: «Elves» 🟢, «Spy Combo» 🟢.
            colors = _from_color_emoji(archetype.color_emoji or "")
        if colors is None:
            colors = self._ask_llm(archetype.name)
        if colors is None:
            return COLORLESS

        archetype.color_identity = colors
        return colors

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
        if not isinstance(colors, str):
            logger.warning("[deck_colors] LLM вернула не-строку в colors для %r: %r", name, answer)
            return None
        colors = colors.strip().upper()
        if colors == "C":
            return COLORLESS
        # Строгая проверка, а не canon(): canon просто выкидывает лишние буквы, поэтому
        # «Rakdos» превратился бы в «R», а «Grixis» в «RG» — и осел бы в кэше навсегда.
        if not colors or not all(c in WUBRG for c in colors):
            logger.warning("[deck_colors] LLM вернула не цвета WUBRG для %r: %r", name, answer)
            return None
        return canon(colors)
