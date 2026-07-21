"""Общий («канонический») тип колоды из свободного названия архетипа.

Игроки пишут одну и ту же колоду по-разному: регистр («Uw Familiars»), эмодзи
(«🔵⚫️🧚 Dimir Faeries»), язык («Mono U Феи»), гильдия vs буквы («Rakdos madness» /
«BR madness»), синонимы («Blue Terror» / «Blue Delver»; «White Aggro» / «WW»; «Jund
Midrange» / «Jund Wildfire»). Сводим к общему типу: <цвет> <базовый архетип>.

Формат цвета — как принято у игроков (решения владельца):
- моно — цветом-словом: «Red Madness», «Blue Terror»;
- 2 цвета — буквами в порядке WUBRG, но Азориус пишем «UW» (не «WU»): «BR Madness», «UW Familiars»;
- 3 цвета — гильдией/клином словом: «Jund Midrange», «Grixis Affinity».

Правила базы:
- delver → terror; «Jund wildfire» → «Jund Midrange» (только Jund; «Temur Wildfire» — отдельно);
- Феи/Терроры/Троны по цвету НЕ сливаем; «Red Madness» и «White Heroic» — отдельные типы;
- «Caw» = Azorius (UW); «Inside Out» без цвета → WR (Boros); «Ponza/Landfall» → RG Ramp.

Только локальный разбор строки — сети нет, можно звать из event loop.
"""

from __future__ import annotations

import re
import unicodedata

WUBRG = "WUBRG"

# 2-цветные гильдии → буквы (как их пишут игроки: Азориус — UW, остальные — порядок WUBRG)
_GUILD2 = {
    "azorius": "UW",
    "dimir": "UB",
    "rakdos": "BR",
    "golgari": "BG",
    "gruul": "RG",
    "boros": "WR",
    "orzhov": "WB",
    "izzet": "UR",
    "selesnya": "WG",
    "simic": "UG",
}
# 3-цветные клинья/шарды — общий тип пишем словом
_WEDGE3 = {"jeskai", "grixis", "jund", "naya", "abzan", "temur", "bant", "esper", "mardu", "sultai"}
_WEDGE_BY_LETTERS = {
    "WUR": "Jeskai",
    "UBR": "Grixis",
    "BRG": "Jund",
    "WRG": "Naya",
    "WBG": "Abzan",
    "URG": "Temur",
    "WUG": "Bant",
    "WUB": "Esper",
    "WBR": "Mardu",
    "UBG": "Sultai",
}
_MONO_WORD = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
_LETTER_WORD = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green"}

# База архетипа: ключевое слово → каноничная база. Порядок важен — сначала специфичные.
_BASE_RULES = [
    (r"inside\s*out", "Inside Out"),
    (r"soul sisters", "Soul Sisters"),
    (r"terror|delver", "Terror"),
    (r"madness", "Madness"),
    (r"affinity", "Affinity"),
    (r"fams|familiars", "Familiars"),
    (r"faeries|faerie|fairies|fairy|фе[ий]", "Faeries"),
    (r"gates", "Gates"),
    (r"pestilence", "Pestilence"),
    (r"gardens", "Gardens"),
    (r"ephemerate", "Ephemerate"),
    (r"heroic", "Heroic"),
    (r"metalcraft", "Metalcraft"),
    (r"weenie|aggro|\bww\b", "Aggro"),
    (r"blade", "Blade"),
    (r"tribe", "Tribe"),
    (r"aristocrats", "Aristocrats"),
    (r"sacrifice", "Sacrifice"),
    (r"devotion|devoution", "Devotion"),
    (r"burn", "Burn"),
    (r"slime", "Slime"),
    (r"stompy", "Stompy"),
    (r"infect", "Infect"),
    (r"skred", "Skred"),
    (r"ponza|ramp|landfall", "Ramp"),
    (r"rally", "Rally"),
    (r"synth|moxite", "Synth"),
    (r"\bfog\b", "Fog"),
    (r"\bmill\b", "Mill"),
    (r"control", "Control"),
    (r"rogue", "Rogue"),
    (r"com-bow", "Com-Bow"),
    (r"counters", "Counters"),
    (r"arcane|abjure", "Control"),
    (r"food", "Pestilence"),
    (r"combo", "Combo"),
]

# Колоды с фиксированным именем (цвет игнорируем — он у них не различает деку).
_FIXED = [
    (r"spy|walls", "Spy Walls"),
    (r"bogles", "Bogles"),
    (r"\belves\b", "Elves"),
    (r"ruby storm|rg storm", "Ruby Storm"),
    (r"poison", "Poison Storm"),
    (r"pizza", "Pizza Combo"),
    (r"turbo fog", "Turbo Fog"),
]

# База без цвета в названии → цвет по умолчанию (эти деки практически всегда одноцветны).
_DEFAULT_COLOR = {"Inside Out": "WR", "Ramp": "RG", "Tribe": "WR"}


def _norm(name: str) -> str:
    """Нижний уровень шума: срезаем эмодзи/модификаторы, ё→е, схлопываем пробелы."""
    s = "".join(c for c in (name or "") if not unicodedata.category(c).startswith(("So", "Sk", "Cs", "Cf")))
    s = s.replace("ё", "е").replace("Ё", "Е")
    return re.sub(r"\s+", " ", s).strip()


def _canon(letters: str) -> str:
    """Набор цветов → код: {W,U}=UW (как у игроков), остальное в порядке WUBRG."""
    s = {c for c in letters.upper() if c in WUBRG}
    if s == {"W", "U"}:
        return "UW"
    return "".join(c for c in WUBRG if c in s)


def _colors(name: str) -> str:
    """Код цвета из названия: гильдия/клин-слово, «caw», моно-слово, буквы WUBRG. '' — не нашли."""
    low = name.lower()
    if "caw" in low:  # Caw (Azorius-стратегия)
        return "UW"
    for g in _WEDGE3:
        if g in low:
            return {v: k for k, v in _WEDGE_BY_LETTERS.items()}[g.capitalize()]
    for g, code in _GUILD2.items():
        if g in low:
            return code
    if re.search(r"\b5c\b|\bfive colou?r", low):
        return "5C"
    for w, letter in _MONO_WORD.items():
        if re.search(rf"\bmono {w}\b|\b{w}\b", low):
            return letter
    for tok in re.findall(r"\b[wubrg]{1,3}\b", low):
        up = tok.upper()
        if len(set(up)) == len(up):
            return _canon(up)
    return ""


def _color_prefix(code: str) -> str | None:
    """Код цвета → как писать в общем типе: моно-слово / буквы / гильдия-слово."""
    if not code:
        return None
    if code == "5C":
        return "5C"
    n = len(code)
    if n == 1:
        return _LETTER_WORD[code]
    if n == 2:
        return code  # уже в нужной форме (UW/UB/BR/…)
    if n == 3:
        return _WEDGE_BY_LETTERS.get(_canon(code), code)
    return code  # 4 цвета — буквами


def _tron(low: str) -> str | None:
    if "tron" not in low:
        return None
    for sub in ("flicker", "monster", "altar"):
        if sub in low:
            return f"{sub.capitalize()} Tron"
    if re.search(r"\b5c\b|five colou?r", low):
        return "5C Tron"
    return "Tron"


def _base(low: str) -> tuple[str | None, bool]:
    """(база, fixed). fixed=True — имя фиксированное, цвет не приписываем."""
    for pat, canon in _FIXED:
        if re.search(pat, low):
            return canon, True
    # «Jund wildfire/midrange» → Midrange; для остальных цветов «Wildfire» — отдельная база
    if "jund" in low and ("wildfire" in low or "midrange" in low):
        return "Midrange", False
    if "wildfire" in low:
        return "Wildfire", False
    if "midrange" in low:
        return "Midrange", False
    for pat, canon in _BASE_RULES:
        if re.search(pat, low):
            return canon, False
    return None, False


def general_archetype(name: str) -> str | None:
    """Общий тип колоды из свободного названия, либо None если не распознали.

    Примеры: «Blue Delver» → «Blue Terror»; «Rakdos madness» → «BR Madness»;
    «Jund Wildfire» → «Jund Midrange»; «Uw fams» → «UW Familiars»; «Caw Gates» → «UW Gates».
    """
    n = _norm(name)
    if not n:
        return None
    low = n.lower()

    tron = _tron(low)
    if tron:
        return tron

    base, fixed = _base(low)
    if fixed:
        return base
    if base is None:
        return None

    prefix = _color_prefix(_colors(n))
    if prefix is None:
        prefix = _color_prefix(_DEFAULT_COLOR.get(base, ""))
    if prefix is None:
        return base  # цвет не определён — общий тип по базе (напр. «Gates»)
    return f"{prefix} {base}"


def backfill_general_names(db, *, only_missing: bool = True) -> int:
    """Проставить general_name у архетипов в БД. Возвращает число обновлённых.

    only_missing=True — только там, где ещё пусто (безопасный бэкофилл после миграции);
    False — пересчитать все (напр. после правки правил).
    """
    from core import models  # noqa: PLC0415 — избегаем циклического импорта на уровне модуля

    q = db.query(models.Archetype)
    if only_missing:
        q = q.filter(models.Archetype.general_name.is_(None))
    updated = 0
    for arch in q.all():
        value = general_archetype(arch.name)
        if value != arch.general_name:
            arch.general_name = value
            updated += 1
    if updated:
        db.commit()
    return updated
