"""Tests for services.deck_mapping.general_archetype — свободное название → общий тип."""

import pytest

from services.deck_mapping import general_archetype, macro_archetype

# Фактический срез production-турнира «Edinorog Pauper 06.08.2026» (#65).
# Это главный регрессионный набор: правила ниже должны объяснять реальные записи игроков,
# а не только подобранные разработчиком синтетические строки.
EDINOROG_2026_08_06_GENERAL_NAMES = [
    ("Blue Terror", "Blue Terror"),
    ("Flicker Tron", "Flicker Tron"),
    ("Spy Walls", "Spy Walls"),
    ("Jund Wildfire", "Jund Midrange"),
    ("Red Rally", "Red Rally"),
    ("Mono U Феи", "Blue Faeries"),
    ("Golgari gardens", "BG Gardens"),
    ("Orzhov Blade", "WB Blade"),
    ("Altar Tron", "Altar Tron"),
    ("Bow Combo", "Combo"),
    ("Walls combo", "Spy Walls"),
    ("Selesnya Turbo Initiative", "WG Turbo Initiative"),
    ("Golgari Pestilence", "BG Pestilence"),
    ("Izzet Faeries", "UR Faeries"),
    ("Grixis Affinity", "Grixis Affinity"),
    ("Rakdos Madness", "BR Madness"),
    ("Blue Delver", "Blue Terror"),
    ("Gardens", "BG Gardens"),
    ("White Weenie", "White Aggro"),
    ("White Heroic", "White Heroic"),
    ("Blue Terror", "Blue Terror"),
    ("mardu synth", "Mardu Synth"),
    ("golgary gardens", "BG Gardens"),
    ("White Tron", "Tron"),
]


@pytest.mark.parametrize("raw,expected", EDINOROG_2026_08_06_GENERAL_NAMES)
def test_edinorog_2026_08_06_real_decks_general_name(raw, expected):
    assert general_archetype(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # цвет: моно — словом, 2 — буквами (Азориус UW), 3 — гильдией
        ("Rakdos madness", "BR Madness"),
        ("BR madness ⚫️🔴👹", "BR Madness"),  # регистр + эмодзи
        ("Br madness", "BR Madness"),
        ("Red Madness", "Red Madness"),  # моно-R — отдельная (не BR)
        ("Grixis Affinity", "Grixis Affinity"),  # 3 цвета — словом
        ("Grixis Afinity", "Grixis Affinity"),
        ("Grixis Afvinoty", "Grixis Affinity"),  # длинное слово: две ошибки
        ("Dimir Affinity", "UB Affinity"),  # 2 цвета — буквами
        ("Uw Familiars", "UW Familiars"),  # регистр
        ("UW fams", "UW Familiars"),  # синоним fams
        ("Azorius Familiars", "UW Familiars"),  # гильдия→буквы (Азориус UW)
        # delver = terror; терроры по цвету НЕ сливаем
        ("Blue Delver", "Blue Terror"),
        ("Blue Terror", "Blue Terror"),
        ("Dimir Terror", "UB Terror"),
        ("Simic Terror", "UG Terror"),
        # jund wildfire = jund midrange; temur wildfire — отдельный
        ("Jund Wildfire", "Jund Midrange"),
        ("Jund Midrange", "Jund Midrange"),
        ("Temur Wildfire", "Temur Wildfire"),
        # white aggro-семья; heroic отдельно
        ("White Weenie", "White Aggro"),
        ("White Aggro", "White Aggro"),
        ("White Heroic", "White Heroic"),
        ("Mono W heroic", "White Heroic"),
        # феи по цвету НЕ сливаем
        ("Dimir Faeries", "UB Faeries"),
        ("Ub Faerie", "UB Faeries"),
        ("🔵⚫️🧚 Dimir Faeries", "UB Faeries"),
        ("Mono U faeries", "Blue Faeries"),
        ("Mono U Феи", "Blue Faeries"),  # RU → faeries
        # троны — по подтипу раздельно
        ("Flicker Tron", "Flicker Tron"),
        ("Flicker tron", "Flicker Tron"),
        ("Flicker trno", "Flicker Tron"),
        ("Monster Tron", "Monster Tron"),
        ("Altar tron", "Altar Tron"),
        ("Tron", "Tron"),
        # gates по цвету; Caw = UW; голый Gates — без цвета
        ("Caw Gates", "UW Gates"),
        ("Naya gates", "Naya Gates"),
        ("Selesnya Gates", "WG Gates"),
        ("Gates", "Gates"),
        # решения владельца
        ("Inside out", "WR Inside Out"),
        ("Boros Inside Out", "WR Inside Out"),
        ("Gruul Landfall", "RG Ramp"),
        ("Ponza", "RG Ramp"),
        ("RG ramp", "RG Ramp"),
        ("Rg storm", "Ruby Storm"),
        ("Ruby storm🔴🟢🪲👺", "Ruby Storm"),
        ("Boros Tribe", "WR Tribe"),
        # фиксированные (цвет не приписываем)
        ("🟢🔵🐸 Bogles", "Bogles"),
        ("Elves", "Elves"),
        ("Poison storm", "Poison Storm"),
        ("Spy Walls", "Spy Walls"),
        ("Walls combo", "Spy Walls"),
        # прочее
        ("Orzhov Blade", "WB Blade"),
        ("Golgari Pestilence", "BG Pestilence"),
        ("Golgari gardens", "BG Gardens"),
        ("golgary gardens", "BG Gardens"),
        ("Gardens", "BG Gardens"),
        ("Izzet Gardens", "BG Gardens"),  # у Gardens нет цветовых вариантов
        ("Selesnya Turbo Initiative", "WG Turbo Initiative"),
        ("Izzet Faeries", "UR Faeries"),
        ("Mono Red", None),  # относится только к новому macro_name
        ("Jeskai Ephemerate", "Jeskai Ephemerate"),
        ("Mono G Stompy", "Green Stompy"),
        ("Black Sacrifice", "Black Sacrifice"),
    ],
)
def test_general_archetype(raw, expected):
    assert general_archetype(raw) == expected


def test_case_insensitive_and_emoji_are_ignored():
    assert general_archetype("uW  FaMs") == general_archetype("UW Familiars")


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_empty_returns_none(bad):
    assert general_archetype(bad) is None


@pytest.mark.parametrize("name", ["Grixis Finality", "Throne Combo"])
def test_similar_unrelated_words_do_not_match_priority_families(name):
    assert general_archetype(name) not in {"Affinity", "Tron"}


def test_existing_general_tron_substring_behavior_is_unchanged():
    """Macro feature must not silently alter the pre-existing general-name parser."""
    assert general_archetype("Strong Control") == "Tron"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Blue Teror", "Blue Terror"),
        ("Dimir Faereis", "UB Faeries"),
        ("Golgari Pestilnce", "BG Pestilence"),
        ("gardnes", "BG Gardens"),
        ("White Heroicc", "White Heroic"),
        ("Grixis Afvixoty", None),  # три ошибки — уже не исправляем
        ("Iron Combo", "Combo"),  # короткий Tron не ловит замену
        ("Burm", None),  # короткий Burn не ловит замену
    ],
)
def test_strict_general_fuzzy_allows_only_one_or_two_typos(raw, expected):
    assert general_archetype(raw) == expected


@pytest.mark.parametrize(
    "guild,code",
    [
        ("Golgari", "BG"),
        ("Orzhov", "WB"),
        ("Izzet", "UR"),
        ("Rakdos", "BR"),
        ("Selesnya", "WG"),
    ],
)
def test_tournament_guild_names_become_two_color_codes_for_unknown_decks(guild, code):
    assert general_archetype(f"{guild} New Brew") == f"{code} New Brew"


@pytest.mark.parametrize(
    "general,expected",
    [
        ("BG Gardens", "BG Control"),
        ("BG Pestilence", "BG Control"),
        ("Mono Red", "Burn"),
        ("Burn", "Burn"),
        ("Red Madness", "Burn"),
        ("Red Rally", "Burn"),
        ("BR Madness", "Burn"),
        ("Blue Terror", "Terror"),
        ("UB Terror", "Terror"),
        ("Blue Faeries", "Faeries"),
        ("UB Faeries", "Faeries"),
        ("UR Faeries", None),
        ("Grixis Affinity", "Affinity"),
        ("UB Affinity", "Affinity"),
        ("Affinity", "Affinity"),
        ("Flicker Tron", "Tron"),
        ("Altar Tron", "Tron"),
        ("5C Tron", "Tron"),
        ("Tron", "Tron"),
        (None, None),
    ],
)
def test_macro_archetype(general, expected):
    assert macro_archetype(general) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Grixis Afinity", "Affinity"),
        ("Grixis Affinety", "Affinity"),
        ("Flicker trno", "Tron"),
        ("Blue Teror", "Terror"),
        ("Dimir Faereis", "Faeries"),
        ("gardnes", "BG Control"),
        ("Red Madnes", "Burn"),
        ("Red Bunr", "Burn"),
        ("Burnn", "Burn"),
        ("Grixis Finality", None),
        ("Iron Combo", None),
        ("Burm", None),
        ("Throne Combo", None),
        ("Izzet Faereis", None),
        ("UB Madnes", None),
        ("Affinity Tron", None),
    ],
)
def test_fuzzy_matching_applies_only_to_macro_archetype(raw, expected):
    assert macro_archetype(None, raw) == expected
