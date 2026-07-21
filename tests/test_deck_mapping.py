"""Tests for services.deck_mapping.general_archetype — свободное название → общий тип."""

import pytest

from services.deck_mapping import general_archetype


@pytest.mark.parametrize(
    "raw,expected",
    [
        # цвет: моно — словом, 2 — буквами (Азориус UW), 3 — гильдией
        ("Rakdos madness", "BR Madness"),
        ("BR madness ⚫️🔴👹", "BR Madness"),  # регистр + эмодзи
        ("Br madness", "BR Madness"),
        ("Red Madness", "Red Madness"),  # моно-R — отдельная (не BR)
        ("Grixis Affinity", "Grixis Affinity"),  # 3 цвета — словом
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
