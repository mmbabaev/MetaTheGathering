"""Tests for services.deck_mapping.general_archetype — свободное название → общий тип."""

import pytest

from services.deck_mapping import general_archetype, macro_archetype


@pytest.mark.parametrize(
    "raw,expected",
    [
        # цвет: моно — словом, 2 — буквами (Азориус UW), 3 — гильдией
        ("Rakdos madness", "BR Madness"),
        ("BR madness ⚫️🔴👹", "BR Madness"),  # регистр + эмодзи
        ("Br madness", "BR Madness"),
        ("Red Madness", "Red Madness"),  # моно-R — отдельная (не BR)
        ("Grixis Affinity", "Grixis Affinity"),  # 3 цвета — словом
        ("Grixis Afinity", "Grixis Affinity"),  # пропущенная буква
        ("Grixis Afvinoty", "Grixis Affinity"),  # две ошибочные буквы
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
        ("Flicker trno", "Flicker Tron"),  # переставлены соседние буквы
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
        ("Mono Red", "Mono Red"),
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


@pytest.mark.parametrize("name", ["Grixis Finality", "Strong Control", "Throne Combo"])
def test_similar_unrelated_words_do_not_match_priority_families(name):
    assert general_archetype(name) not in {"Affinity", "Tron"}


@pytest.mark.parametrize(
    "general,expected",
    [
        ("BG Gardens", "BG Control"),
        ("BG Pestilence", "BG Control"),
        ("Mono Red", "Burn"),
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
