"""Tests for deck color identity resolution (services/deck_colors.py)."""

from itertools import combinations

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
        """«Flicker Tron» — синяя колода: маркер «tron» врёт, поэтому цвет берётся из справочника."""
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
    def test_resolves_and_caches_heuristic_result(self, db):
        archetype = ArchetypeService(db).get_or_create_by_name("Boros tribe")

        assert DeckColorResolver(db).resolve(archetype) == "WR"
        assert archetype.color_identity == "WR"  # закэшировано в БД

    def test_cached_value_is_reused(self, db):
        archetype = ArchetypeService(db).get_or_create_by_name("Uzmen")
        archetype.color_identity = "BG"
        db.commit()

        assert DeckColorResolver(db).resolve(archetype) == "BG"

    def test_color_emoji_field_used_when_name_unparseable(self, db):
        """У засеянных архетипов уже есть color_emoji — он и выручает."""
        archetype = ArchetypeService(db).get_or_create_by_name("Uzmen")
        archetype.color_emoji = "🟢"
        db.commit()

        assert DeckColorResolver(db).resolve(archetype) == "G"

    def test_name_wins_over_color_emoji_field(self, db):
        """«Grixis Affinity» помечен ⚙️, но по имени это UBR — имя точнее."""
        archetype = ArchetypeService(db).get_or_create_by_name("Grixis Affinity")
        archetype.color_emoji = "⚙️"
        db.commit()

        assert DeckColorResolver(db).resolve(archetype) == "UBR"

    def test_non_color_emoji_field_is_ignored(self, db):
        """🟤 у «Jund Wildfire» — не цвет MTG, не должен давать ложную идентичность."""
        archetype = ArchetypeService(db).get_or_create_by_name("Uzmen")
        archetype.color_emoji = "🟤"
        db.commit()

        assert DeckColorResolver(db).resolve(archetype) == COLORLESS
        assert archetype.color_identity is None

    def test_unknown_deck_is_colorless_and_not_cached(self, db):
        """Серое не кэшируем: колода переопределится, когда её занесут в справочник."""
        archetype = ArchetypeService(db).get_or_create_by_name("Uzmen")

        assert DeckColorResolver(db).resolve(archetype) == COLORLESS
        assert archetype.color_identity is None

    def test_deck_book_wins_over_stale_cache(self, db):
        """Словарь — источник истины: правка в коде должна применяться сразу,
        не дожидаясь, пока протухнет color_identity в БД."""
        archetype = ArchetypeService(db).get_or_create_by_name("Spy Walls")
        archetype.color_identity = "R"  # устаревшее/ошибочное значение в кэше
        db.commit()

        assert DeckColorResolver(db).resolve(archetype) == "BG"

    def test_deck_book_wins_over_heuristic(self, db):
        """«Walls» эвристика прочитала бы неверно — справочник знает, что это зелёная."""
        walls = ArchetypeService(db).get_or_create_by_name("Walls")
        assert DeckColorResolver(db).resolve(walls) == "G"

    def test_resolve_many_returns_map_by_id(self, db):
        arch_svc = ArchetypeService(db)
        burn = arch_svc.get_or_create_by_name("Red Madness")
        infect = arch_svc.get_or_create_by_name("UG Infect")

        result = DeckColorResolver(db).resolve_many([burn, infect])

        assert result == {burn.id: "R", infect.id: "UG"}
