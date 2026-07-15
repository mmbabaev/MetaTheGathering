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
            # инициалы с заглавной и mono + одна буква — так пишут в реальных названиях
            ("Ub Faerie", "UB"),
            ("Bg pestilence", "BG"),
            ("Mono U faeries", "U"),
            ("BG GARDENS", "BG"),  # «GARDENS» не сбивает — берётся первый подходящий токен
            # эмодзи-пометки цвета от игроков
            ("🔴⚫️👹Goblin combo", "BR"),
            ("🟢🔵🐸 Bogles", "UG"),
            # цветовые слова
            ("Blue Terror", "U"),
            ("Mono Black Devotion", "B"),
            ("White aggro", "W"),
            ("Red Madness", "R"),
            # пять цветов
            ("5c Domain", "WUBRG"),
            ("Five Color Ramp", "WUBRG"),
            # четыре цвета — пишутся через дефис, а токенизатор дефис срезает
            ("Yore-Tiller Aggro", "WUBR"),
            ("Glint-Eye Control", "UBRG"),
            ("Witch-Maw", "WUBG"),
        ],
    )
    def test_parses_known_names(self, name, expected):
        assert parse_color_identity(name) == expected

    @pytest.mark.parametrize("name", ["Gates", "Spy Combo", "Familiars", ""])
    def test_returns_none_for_unparseable(self, name):
        assert parse_color_identity(name) is None

    @pytest.mark.parametrize("name", ["Flicker Tron", "Affinity", "Altar Tron"])
    def test_artifact_names_are_not_forced_colorless(self, name):
        """«Flicker Tron» — синяя колода. Маркер «tron» врёт, поэтому решает LLM, а не он."""
        assert parse_color_identity(name) is None

    @pytest.mark.parametrize("name", ["grub deck", "Grub deck"])
    def test_words_of_wubrg_letters_are_not_read_as_initials(self, name):
        """«grub» состоит из букв WUBRG, но это слово, а не инициалы."""
        assert parse_color_identity(name) is None

    def test_single_letter_needs_mono(self):
        """Одинокая «U» — цвет только рядом с «mono», иначе это инициал имени."""
        assert parse_color_identity("U faeries") is None
        assert parse_color_identity("Mono U faeries") == "U"

    def test_name_wins_over_emoji(self):
        """Имя точнее эмодзи: 🔵 тут флейвор, а Grixis — реальные цвета."""
        assert parse_color_identity("🔵 Grixis Affinity") == "UBR"


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
        archetype = ArchetypeService(db).get_or_create_by_name("Uzmen")
        archetype.color_identity = "BG"
        db.commit()
        llm = MagicMock()
        llm.enabled = True

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == "BG"
        llm.complete.assert_not_called()

    def test_llm_fallback_for_unparseable_name(self, db):
        archetype = ArchetypeService(db).get_or_create_by_name("Uzmen")
        llm = MagicMock()
        llm.enabled = True
        llm.complete.return_value = '{"colors":"BG"}'

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == "BG"
        assert archetype.color_identity == "BG"
        llm.complete.assert_called_once()

    def test_color_emoji_field_used_when_name_unparseable(self, db):
        """У засеянных архетипов уже есть color_emoji — используем, прежде чем звать LLM."""
        archetype = ArchetypeService(db).get_or_create_by_name("Uzmen")
        archetype.color_emoji = "🟢"
        db.commit()
        llm = MagicMock()
        llm.enabled = True

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == "G"
        llm.complete.assert_not_called()

    def test_name_wins_over_color_emoji_field(self, db):
        """«Grixis Affinity» помечен ⚙️, но по имени это UBR — имя точнее."""
        archetype = ArchetypeService(db).get_or_create_by_name("Grixis Affinity")
        archetype.color_emoji = "⚙️"
        db.commit()

        assert DeckColorResolver(db, llm=MagicMock(enabled=False)).resolve(archetype) == "UBR"

    def test_non_color_emoji_field_is_ignored(self, db, disabled_llm):
        """🟤 у «Jund Wildfire» — не цвет MTG, не должен давать ложную идентичность."""
        archetype = ArchetypeService(db).get_or_create_by_name("Uzmen")
        archetype.color_emoji = "🟤"
        db.commit()

        assert DeckColorResolver(db, llm=disabled_llm).resolve(archetype) == COLORLESS
        assert archetype.color_identity is None

    def test_llm_not_called_when_heuristic_succeeds(self, db):
        archetype = ArchetypeService(db).get_or_create_by_name("Mono Black Devotion")
        llm = MagicMock()
        llm.enabled = True

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == "B"
        llm.complete.assert_not_called()

    def test_llm_answer_c_means_colorless(self, db):
        archetype = ArchetypeService(db).get_or_create_by_name("Uzmen")
        llm = MagicMock()
        llm.enabled = True
        llm.complete.return_value = '{"colors":"C"}'

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == COLORLESS
        assert archetype.color_identity == COLORLESS

    def test_llm_answer_is_canonicalized(self, db):
        archetype = ArchetypeService(db).get_or_create_by_name("Uzmen")
        llm = MagicMock()
        llm.enabled = True
        llm.complete.return_value = 'Вот ответ: {"colors":"gu"}'

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == "UG"

    def test_artifact_name_reaches_llm(self, db):
        """Раньше маркер «tron»/«affinity» кэшировал такое имя серым навсегда, мимо LLM."""
        archetype = ArchetypeService(db).get_or_create_by_name("Affinity")
        llm = MagicMock()
        llm.enabled = True
        llm.complete.return_value = '{"colors":"BR"}'

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == "BR"
        llm.complete.assert_called_once()

    def test_deck_book_wins_over_stale_cache(self, db):
        """Словарь — источник истины: правка в коде должна применяться сразу,
        не дожидаясь, пока протухнет color_identity в БД."""
        archetype = ArchetypeService(db).get_or_create_by_name("Spy Walls")
        archetype.color_identity = "R"  # устаревшее/ошибочное значение в кэше
        db.commit()
        llm = MagicMock()
        llm.enabled = True

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == "BG"
        llm.complete.assert_not_called()

    def test_deck_book_wins_over_heuristic(self, db, disabled_llm):
        """«Poison Storm» эвристикой не читается, а «Walls» — читалось бы неверно."""
        walls = ArchetypeService(db).get_or_create_by_name("Walls")
        assert DeckColorResolver(db, llm=disabled_llm).resolve(walls) == "G"

    @pytest.mark.parametrize(
        "answer",
        [
            "не знаю",
            "{битый json",
            '{"colors":123}',
            "",
            '{"colors":"Rakdos"}',  # не буквы WUBRG — canon() вытащил бы «R» и закэшировал
            '{"colors":"Grixis"}',  # canon() вытащил бы «RG» вместо верного UBR
        ],
    )
    def test_bad_llm_answer_falls_back_to_colorless_without_caching(self, db, answer):
        archetype = ArchetypeService(db).get_or_create_by_name("Uzmen")
        llm = MagicMock()
        llm.enabled = True
        llm.complete.return_value = answer

        assert DeckColorResolver(db, llm=llm).resolve(archetype) == COLORLESS
        # NULL, а не "": архетип переопределится, когда LLM починят
        assert archetype.color_identity is None

    def test_default_is_not_cached_when_llm_disabled(self, db, disabled_llm):
        archetype = ArchetypeService(db).get_or_create_by_name("Uzmen")

        assert DeckColorResolver(db, llm=disabled_llm).resolve(archetype) == COLORLESS
        assert archetype.color_identity is None

    def test_resolve_many_returns_map_by_id(self, db, disabled_llm):
        arch_svc = ArchetypeService(db)
        burn = arch_svc.get_or_create_by_name("Red Madness")
        infect = arch_svc.get_or_create_by_name("UG Infect")

        result = DeckColorResolver(db, llm=disabled_llm).resolve_many([burn, infect])

        assert result == {burn.id: "R", infect.id: "UG"}
