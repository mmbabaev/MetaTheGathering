"""Tests for the curated Pauper deck book (services/deck_book.py)."""

import pytest

from services.deck_book import DECK_BOOK, WUBRG_OK, lookup_deck, normalize_deck_name


class TestNormalizeDeckName:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Caw-Gates", "caw gates"),
            ("Caw Gates", "caw gates"),
            ("caw gates", "caw gates"),
            ("🟢🔵🐸 Bogles", "bogles"),
            ("Flicker tron", "flicker tron"),
            ("  Rakdos   Madness ", "rakdos madness"),
            ("Bg pestilence ⚫️🟢🌱💀", "bg pestilence"),
        ],
    )
    def test_normalizes(self, raw, expected):
        assert normalize_deck_name(raw) == expected

    @pytest.mark.parametrize(
        "a,b",
        [
            ("Caw-Gates", "Caw Gates"),
            ("Flicker Tron", "Flicker tron"),
            ("Altar Tron", "Altar tron"),
            ("Mono U faeries", "Mono U Faeries"),
            ("Rakdos Madness", "Rakdos madness"),
            ("🟢🔵🐸 Bogles", "Bogles"),
        ],
    )
    def test_prod_duplicates_collapse(self, a, b):
        """В проде эти пары лежат разными архетипами и дробили бы график."""
        assert normalize_deck_name(a) == normalize_deck_name(b)


class TestLookupDeck:
    @pytest.mark.parametrize(
        "name,display,colors",
        [
            # цвета подтверждены игроком — из названия их не вывести
            ("Elves", "Elves", "G"),
            ("Poison Storm", "Poison Storm", "UG"),
            ("Cycle Storm", "Cycle Storm", "RG"),
            ("Turbo Fog", "Turbo Fog", "WUG"),
            ("Gates", "Gates", "WUG"),
            ("Walls", "Walls", "G"),
            ("Slivers", "Slivers", "WUBRG"),
            ("infect", "Infect", "UG"),
            ("Ponza", "Ponza", "RG"),
            ("Rogue", "Rogue", "UB"),
        ],
    )
    def test_known_colors(self, name, display, colors):
        deck = lookup_deck(name)
        assert (deck.display, deck.colors) == (display, colors)

    @pytest.mark.parametrize("name", ["Spy", "Spy Walls", "Spy Combo"])
    def test_spy_family_is_one_group(self, name):
        assert lookup_deck(name) == lookup_deck("Spy Combo")
        assert lookup_deck(name).display == "Spy Combo"
        assert lookup_deck(name).colors == "BG"

    @pytest.mark.parametrize("name", ["Tron", "Flicker Tron", "Monster Tron", "Altar Tron", "Altar tron"])
    def test_tron_family_is_one_group(self, name):
        assert lookup_deck(name).display == "Tron"

    @pytest.mark.parametrize("name", ["Bogles", "Boggles", "🟢🔵🐸 Bogles"])
    def test_bogles_variants_are_one_group(self, name):
        assert lookup_deck(name).display == "Bogles"
        assert lookup_deck(name).colors == "GW"

    def test_caw_gates_variants(self):
        assert lookup_deck("Caw Gates") == lookup_deck("Caw-Gates")
        assert lookup_deck("Caw Gates").colors == "WU"

    def test_bare_gates_is_not_caw_gates(self):
        """«Gates» и «Caw-Gates» — разные колоды и разные цвета."""
        assert lookup_deck("Gates") != lookup_deck("Caw-Gates")

    @pytest.mark.parametrize("name", ["Uzmen", "Blue Terror", "Grixis Affinity", "Совсем незнакомая колода"])
    def test_unknown_decks_are_absent(self, name):
        """Чего не знаем — не выдумываем: цвет определит эвристика или он останется серым."""
        assert lookup_deck(name) is None


class TestBookIntegrity:
    def test_colors_are_valid_wubrg(self):
        bad = {deck.display: deck.colors for deck in DECK_BOOK.values() if not WUBRG_OK.fullmatch(deck.colors)}
        assert bad == {}

    def test_keys_are_normalized(self):
        assert all(key == normalize_deck_name(key) for key in DECK_BOOK)
