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
    "golgary": "BG",  # частая турнирная опечатка
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
    (r"\bfam\b|fams|familiars", "Familiars"),
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
    (r"\bsac\b|sacrifice", "Sacrifice"),
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
    # В Pauper «Gardens» — всегда BG Gardens; цветовых вариантов этой деки нет.
    # Правило намеренно сильнее написанного игроком цвета/гильдии.
    (r"gardens", "BG Gardens"),
    # Spy (комбо через Balustrade Spy), Spy Walls и Walls Combo — разные колоды.
    # Более конкретный Spy Walls проверяем первым, потому что он содержит оба маркера.
    (r"\bspy\s+walls\b", "Spy Walls"),
    (r"\bwalls\b", "Walls Combo"),
    (r"\bspy\b", "Spy"),
    (r"bogles", "Bogles"),
    (r"\belves\b", "Elves"),
    (r"ruby storm|rg storm", "Ruby Storm"),
    (r"poison", "Poison Storm"),
    (r"pizza", "Pizza Combo"),
    (r"turbo fog", "Turbo Fog"),
]

# Опечатки ищем только по явным словам-маркерам, а не по полным названиям. Значение:
# (каноническая база/имя, fixed — нужно ли игнорировать цветовой префикс).
_FUZZY_GENERAL_ALIASES = {
    "terror": ("Terror", False),
    "delver": ("Terror", False),
    "madness": ("Madness", False),
    "affinity": ("Affinity", False),
    "familiars": ("Familiars", False),
    "faeries": ("Faeries", False),
    "faerie": ("Faeries", False),
    "fairies": ("Faeries", False),
    "fairy": ("Faeries", False),
    "gates": ("Gates", False),
    "pestilence": ("Pestilence", False),
    "gardens": ("BG Gardens", True),
    "ephemerate": ("Ephemerate", False),
    "heroic": ("Heroic", False),
    "metalcraft": ("Metalcraft", False),
    "weenie": ("Aggro", False),
    "aggro": ("Aggro", False),
    "blade": ("Blade", False),
    "tribe": ("Tribe", False),
    "aristocrats": ("Aristocrats", False),
    "sacrifice": ("Sacrifice", False),
    "devotion": ("Devotion", False),
    "burn": ("Burn", False),
    "slime": ("Slime", False),
    "stompy": ("Stompy", False),
    "infect": ("Infect", False),
    "skred": ("Skred", False),
    "ponza": ("Ramp", False),
    "landfall": ("Ramp", False),
    "rally": ("Rally", False),
    "synth": ("Synth", False),
    "moxite": ("Synth", False),
    "control": ("Control", False),
    "rogue": ("Rogue", False),
    "counters": ("Counters", False),
    "arcane": ("Control", False),
    "abjure": ("Control", False),
    "combo": ("Combo", False),
    "walls": ("Walls Combo", True),
    "bogles": ("Bogles", True),
    "elves": ("Elves", True),
    "poison": ("Poison Storm", True),
    "pizza": ("Pizza Combo", True),
}

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
        if re.search(rf"\bmono[\s_-]*{w}\b|\b{w}\b", low):
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


def _damerau_levenshtein(left: str, right: str) -> int:
    """Редакционное расстояние с одной операцией за перестановку соседних букв."""
    rows = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for i in range(len(left) + 1):
        rows[i][0] = i
    for j in range(len(right) + 1):
        rows[0][j] = j
    for i in range(1, len(left) + 1):
        for j in range(1, len(right) + 1):
            cost = left[i - 1] != right[j - 1]
            rows[i][j] = min(
                rows[i - 1][j] + 1,
                rows[i][j - 1] + 1,
                rows[i - 1][j - 1] + cost,
            )
            if i > 1 and j > 1 and left[i - 1] == right[j - 2] and left[i - 2] == right[j - 1]:
                rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)
    return rows[-1][-1]


def _is_adjacent_transposition(left: str, right: str) -> bool:
    """Отличаются ли слова только перестановкой одной пары соседних букв."""
    if len(left) != len(right):
        return False
    different = [i for i, (a, b) in enumerate(zip(left, right)) if a != b]
    return (
        len(different) == 2
        and different[1] == different[0] + 1
        and left[different[0]] == right[different[1]]
        and left[different[1]] == right[different[0]]
    )


def _one_typo_keyword(text: str, keyword: str) -> bool:
    """Универсальный macro-fuzzy: одна ошибка, с защитой коротких слов от замен."""
    for token in re.findall(r"[a-z]+", text.casefold()):
        distance = _damerau_levenshtein(token, keyword)
        if distance == 0:
            return True
        if distance != 1:
            continue
        if min(len(token), len(keyword)) >= 5:
            return True
        # В коротком слове разрешаем вставку/удаление или явную перестановку, но не
        # замену одной буквы: иначе ``iron`` автоматически становился бы Tron.
        if len(token) != len(keyword) or _is_adjacent_transposition(token, keyword):
            return True
    return False


def _strict_general_keyword(text: str, keyword: str) -> bool:
    """Жёсткий general-fuzzy: 1 ошибка, 2 только у слов длиной от 8 букв."""
    for token in re.findall(r"[a-z]+", text.casefold()):
        distance = _damerau_levenshtein(token, keyword)
        if distance == 0:
            return True
        allowed = 2 if len(keyword) >= 8 and len(token) >= 6 else 1
        if distance > allowed:
            continue
        if min(len(token), len(keyword)) >= 5:
            return True
        if distance == 1 and (len(token) != len(keyword) or _is_adjacent_transposition(token, keyword)):
            return True
    return False


def _fuzzy_general_base(low: str) -> tuple[str | None, bool]:
    """Единственная уверенная каноническая база по словам с 1–2 опечатками."""
    candidates = {target for alias, target in _FUZZY_GENERAL_ALIASES.items() if _strict_general_keyword(low, alias)}
    return next(iter(candidates)) if len(candidates) == 1 else (None, False)


def _fuzzy_macro_from_raw(raw_name: str | None) -> str | None:
    """Макрогруппа из исходного имени по общему правилу одной опечатки."""
    if not raw_name:
        return None
    colors = _colors(_norm(raw_name))
    candidates: set[str] = set()
    if _norm(raw_name).casefold() == "mono red":
        candidates.add("Burn")
    if _one_typo_keyword(raw_name, "affinity"):
        candidates.add("Affinity")
    if _one_typo_keyword(raw_name, "tron"):
        candidates.add("Tron")
    if _one_typo_keyword(raw_name, "gardens"):
        candidates.add("BG Control")  # у Gardens нет цветовых вариантов
    if _one_typo_keyword(raw_name, "pestilence") and colors == "BG":
        candidates.add("BG Control")
    if _one_typo_keyword(raw_name, "burn"):
        candidates.add("Burn")
    if _one_typo_keyword(raw_name, "madness") and colors in {"R", "BR"}:
        candidates.add("Burn")
    if _one_typo_keyword(raw_name, "rally") and colors == "R":
        candidates.add("Burn")
    if _one_typo_keyword(raw_name, "bogles"):
        candidates.add("Bogles")
    if _one_typo_keyword(raw_name, "ephemerate"):
        candidates.add("Ephemerate")
    if _one_typo_keyword(raw_name, "spy"):
        candidates.add("Spy")
    elif _one_typo_keyword(raw_name, "walls"):
        candidates.add("Walls")
    if _one_typo_keyword(raw_name, "sacrifice"):
        candidates.add("Sacrifice")
    if (_one_typo_keyword(raw_name, "terror") or _one_typo_keyword(raw_name, "delver")) and colors in {"U", "UB"}:
        candidates.add("Terror")
    if any(
        _one_typo_keyword(raw_name, keyword) for keyword in ("faeries", "faerie", "fairies", "fairy")
    ) and colors in {"U", "UB"}:
        candidates.add("Faeries")
    return next(iter(candidates)) if len(candidates) == 1 else None


def _tron(low: str) -> str | None:
    if "tron" not in low and not _strict_general_keyword(low, "tron"):
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
    return _fuzzy_general_base(low)


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
        # Даже если новая стратегия ещё не добавлена в _BASE_RULES, гильдию всё равно
        # нормализуем в двухцветный код: «Selesnya Turbo Initiative» →
        # «WG Turbo Initiative». Так новые названия не создают отдельные варианты только
        # из-за записи цвета словом.
        for guild, code in _GUILD2.items():
            match = re.search(rf"\b{guild}\b", n, flags=re.IGNORECASE)
            if match:
                remainder = re.sub(r"[\s_\-/]+", " ", f"{n[: match.start()]} {n[match.end() :]}").strip()
                return f"{code} {remainder.title()}" if remainder else code
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


def macro_archetype(general_name: str | None, raw_name: str | None = None) -> str | None:
    """Крупная стратегическая группа поверх канонического типа колоды.

    Это отдельный экспериментальный слой: ``general_name`` продолжает различать, например,
    BG Gardens и BG Pestilence, а здесь обе колоды попадают в BG Control.
    """
    # Fuzzy относится только к макроархетипу: исходное имя и general_name не меняются.
    fuzzy = _fuzzy_macro_from_raw(raw_name or general_name)
    if fuzzy:
        return fuzzy
    if not general_name:
        return None
    name = general_name.casefold().strip()
    if "affinity" in name:
        return "Affinity"
    if re.search(r"\btron\b", name):
        return "Tron"
    if name in {"bg gardens", "bg pestilence"}:
        return "BG Control"
    if name in {"burn", "mono red", "red madness", "red rally", "red burn", "br madness"}:
        return "Burn"
    if name in {"blue terror", "ub terror"}:
        return "Terror"
    if name in {"blue faeries", "ub faeries"}:
        return "Faeries"
    if name == "bogles":
        return "Bogles"
    if name == "ephemerate" or name.endswith(" ephemerate"):
        return "Ephemerate"
    if name == "spy walls":
        return "Spy"
    if name in {"sacrifice", "black sacrifice"}:
        return "Sacrifice"
    return None


def refresh_archetype_macro(archetype) -> bool:
    """Пересчитать только macro_name; существующие name/general_name не менять."""
    macro = macro_archetype(archetype.general_name, archetype.name)
    changed = archetype.macro_name != macro
    archetype.macro_name = macro
    return changed
