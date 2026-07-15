"""Tests for deck color identity resolution (services/deck_colors.py)."""

from itertools import combinations
from unittest.mock import MagicMock

import pytest

from services.archetype import ArchetypeService
from services.deck_colors import (
    COLORLESS,
    PALETTE,
    WUBRG,
    DeckColorResolver,
    canon,
    hex_for,
    parse_color_identity,
)


class TestCanon:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("GU", "UG"),  # simic — «GU» в разговоре, «UG» в каноне WUBRG
            ("RW", "WR"),
            ("GUR", "URG"),  # temur
            ("uw", "WU"),
            ("UUB", "UB"),  # дубли схлопываются
            ("", ""),
            ("XYZ", ""),  # не-цвета отбрасываются
        ],
    )
    def test_canonicalizes(self, raw, expected):
        assert canon(raw) == expected


class TestParseColorIdentity:
    @pytest.mark.parametrize(
        "name,expected",
        [
            # гильдии / шарды / клинья
            ("Boros tribe", "WR"),
            ("Grixis Affinity", "UBR"),  # гильдия важнее артефактного маркера
            ("Jund Wildfire", "BRG"),
            ("Temur control", "URG"),
            ("Izzet Blitz", "UR"),
            # инициалы
            ("UW Familiars", "WU"),
            ("RG Storm", "RG"),
            ("UG Infect", "UG"),
            ("WW", "W"),  # white weenie
            ("BUG Control", "UBG"),
            # цветовые слова
            ("Blue Terror", "U"),
            ("Mono Black Devotion", "B"),
            ("White aggro", "W"),
            ("Red Madness", "R"),
            # пять цветов
            ("5c Domain", "WUBRG"),
            ("Five Color Ramp", "WUBRG"),
            # бесцветные
            ("Affinity", COLORLESS),
            ("Tron", COLORLESS),
        ],
    )
    def test_parses_known_names(self, name, expected):
        assert parse_color_identity(name) == expected

    @pytest.mark.parametrize("name", ["Gates", "Spy Combo", "Familiars", ""])
    def test_returns_none_for_unparseable(self, name):
        assert parse_color_identity(name) is None

    def test_lowercase_words_are_not_read_as_initials(self):
        """«grub» состоит из букв WUBRG, но это слово, а не инициалы."""
        assert parse_color_identity("grub deck") is None


class TestPalette:
    def test_covers_every_wubrg_subset(self):
        subsets = ["".join(c) for n in range(len(WUBRG) + 1) for c in combinations(WUBRG, n)]
        assert len(subsets) == 32
        missing = [s for s in subsets if canon(s) not in PALETTE]
        assert missing == []

    def test_keys_are_canonical(self):
        assert all(key == canon(key) for key in PALETTE)

    def test_hex_for_unknown_identity_falls_back_to_colorless(self):
        assert hex_for(None) == PALETTE[COLORLESS]
        assert hex_for("ZZ") == PALETTE[COLORLESS]

    def test_hex_for_accepts_non_canonical_order(self):
        assert hex_for("GU") == hex_for("UG")


class TestDeckColorResolver:
    @pytest.fixture
    def disabled_llm(self):
        llm = MagicMock()
        llm.enabled = False
        return llm

    def test_resolves_and_caches_heuristic_result(self, db, disabled_llm):
        archetype = ArchetypeService(db).get_or_create_by_name("Boros tribe")
        resolver = DeckColorResolver(db, llm=disabled_llm)

        assert resolver.resolve(archetype) == "WR"
        assert archetype.color_identity == "WR"  # закэшировано в БД

    def test_cached_value_wins_and_skips_llm(self, db):
        archetype = ArchetypeService(db).get_or_create_by_name("Spy Combo")
        archetype.color_identity = "BG"
        db.commit()
        llm = MagicMock()
        llm.enabled = True

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == "BG"
        llm.complete.assert_not_called()

    def test_llm_fallback_for_unparseable_name(self, db):
        archetype = ArchetypeService(db).get_or_create_by_name("Spy Combo")
        llm = MagicMock()
        llm.enabled = True
        llm.complete.return_value = '{"colors":"BG"}'

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == "BG"
        assert archetype.color_identity == "BG"
        llm.complete.assert_called_once()

    def test_llm_not_called_when_heuristic_succeeds(self, db):
        archetype = ArchetypeService(db).get_or_create_by_name("Mono Black Devotion")
        llm = MagicMock()
        llm.enabled = True

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == "B"
        llm.complete.assert_not_called()

    def test_llm_answer_c_means_colorless(self, db):
        archetype = ArchetypeService(db).get_or_create_by_name("Gates")
        llm = MagicMock()
        llm.enabled = True
        llm.complete.return_value = '{"colors":"C"}'

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == COLORLESS
        assert archetype.color_identity == COLORLESS

    def test_llm_answer_is_canonicalized(self, db):
        archetype = ArchetypeService(db).get_or_create_by_name("Gates")
        llm = MagicMock()
        llm.enabled = True
        llm.complete.return_value = 'Вот ответ: {"colors":"gu"}'

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == "UG"

    @pytest.mark.parametrize("answer", ["не знаю", "{битый json", '{"colors":123}', ""])
    def test_bad_llm_answer_falls_back_to_colorless_without_caching(self, db, answer):
        archetype = ArchetypeService(db).get_or_create_by_name("Gates")
        llm = MagicMock()
        llm.enabled = True
        llm.complete.return_value = answer

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == COLORLESS
        # NULL, а не "": архетип переопределится, когда LLM починят
        assert archetype.color_identity is None

    def test_default_is_not_cached_when_llm_disabled(self, db, disabled_llm):
        archetype = ArchetypeService(db).get_or_create_by_name("Gates")

        assert DeckColorResolver(db, llm=disabled_llm).resolve(archetype) == COLORLESS
        assert archetype.color_identity is None

    def test_resolve_many_returns_map_by_id(self, db, disabled_llm):
        arch_svc = ArchetypeService(db)
        burn = arch_svc.get_or_create_by_name("Red Madness")
        infect = arch_svc.get_or_create_by_name("UG Infect")

        result = DeckColorResolver(db, llm=disabled_llm).resolve_many([burn, infect])

        assert result == {burn.id: "R", infect.id: "UG"}
