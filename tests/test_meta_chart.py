"""Tests for the metagame donut chart (services/meta_chart.py)."""

import io
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image, ImageDraw

from services.archetype import ArchetypeService
from services.deck_book import strip_pictographs
from services.deck_colors import PALETTE, DeckColorResolver
from services.meta_chart import (
    WIDTH,
    ChartSector,
    MetaChartService,
    build_subtitle,
    plural_decks,
    render_sectors,
)


@pytest.fixture
def disabled_llm():
    llm = MagicMock()
    llm.enabled = False
    return llm


@pytest.fixture
def chart_svc(db, disabled_llm):
    return MetaChartService(db, colors=DeckColorResolver(db, llm=disabled_llm))


def _register(svc, user_svc, arch_svc, tournament, tg_id, deck_name):
    user = user_svc.get_or_create(tg_id=tg_id, username=f"u{tg_id}", first_name=f"U{tg_id}")
    archetype = arch_svc.get_or_create_by_name(deck_name)
    svc.register_participant(tournament_id=tournament.id, user_id=user.id, archetype_id=archetype.id)


class TestPluralDecks:
    @pytest.mark.parametrize(
        "n,expected",
        [
            (0, "колод"),
            (1, "колода"),
            (2, "колоды"),
            (4, "колоды"),
            (5, "колод"),
            (11, "колод"),
            (14, "колод"),
            (21, "колода"),
            (22, "колоды"),
            (25, "колод"),
            (101, "колода"),
            (111, "колод"),
        ],
    )
    def test_plural(self, n, expected):
        assert plural_decks(n) == expected


class TestStripPictographs:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            # в DejaVu нет эмодзи — иначе в легенде были бы квадраты-тофу
            ("🔴⚫️👹Goblin combo", "Goblin combo"),
            ("🟢🔵🐸 Bogles", "Bogles"),
            ("Bg pestilence ⚫️🟢🌱💀", "Bg pestilence"),
            ("Blue Terror", "Blue Terror"),
            ("  Red   Madness ", "Red Madness"),
        ],
    )
    def test_strips_pictographs(self, raw, expected):
        assert strip_pictographs(raw) == expected

    def test_name_of_only_emoji_survives(self):
        """Пустая строка в легенде хуже, чем тофу."""
        assert strip_pictographs("🔴🔵") == "🔴🔵"


class TestBuildSubtitle:
    @pytest.mark.parametrize(
        "club,title,expected",
        [
            ("Edinorog", "🦄 Edinorog Pauper 13.07.2026", "Единорог · 13.07.2026"),
            ("Goldfish", "🐠 Goldfish Pauper 02.07.2026", "Goldfish · 02.07.2026"),
            ("edinorog", "Pauper 13.07.2026", "Единорог · 13.07.2026"),  # регистр клуба не важен
            (None, "Pauper 13.07.2026", "13.07.2026"),  # клуба нет — только дата
            ("Goldfish", "Pauper", "Goldfish"),  # даты нет — только клуб
            (None, "Pauper", ""),  # нечего показать
            ("Kara", "Pauper 01.01.2026", "Kara · 01.01.2026"),  # незнакомый клуб — как есть
        ],
    )
    def test_subtitle(self, club, title, expected):
        assert build_subtitle(club, title) == expected

    def test_date_from_title_wins_over_created_at(self):
        """В названии — дата турнира; created_at может отличаться (завели заранее)."""
        assert build_subtitle(None, "Pauper 13.07.2026", datetime(2026, 1, 1)) == "13.07.2026"

    def test_falls_back_to_created_at(self):
        assert build_subtitle("Goldfish", "Pauper", datetime(2026, 7, 2)) == "Goldfish · 02.07.2026"


class TestBuildSectors:
    def test_groups_by_archetype_sorted_by_count(self, chart_svc, svc, user_svc, arch_svc, tournament):
        for tg_id in (1, 2, 3):
            _register(svc, user_svc, arch_svc, tournament, tg_id, "Blue Terror")
        _register(svc, user_svc, arch_svc, tournament, 4, "Red Madness")

        sectors = chart_svc.build_sectors(tournament.id)

        assert [(s.name, s.count) for s in sectors] == [("Blue Terror", 3), ("Red Madness", 1)]

    def test_sector_color_follows_color_identity(self, chart_svc, svc, user_svc, arch_svc, tournament):
        _register(svc, user_svc, arch_svc, tournament, 1, "UG Infect")

        assert chart_svc.build_sectors(tournament.id)[0].color == PALETTE["UG"]

    def test_unresolvable_deck_gets_colorless(self, chart_svc, svc, user_svc, arch_svc, tournament):
        _register(svc, user_svc, arch_svc, tournament, 1, "Uzmen")

        assert chart_svc.build_sectors(tournament.id)[0].color == PALETTE[""]

    def test_deck_book_groups_names_into_one_sector(self, chart_svc, svc, user_svc, arch_svc, tournament):
        """«Spy Walls» + «Spy» + «Spy Combo» — одна колода, названная по-разному."""
        for tg_id, name in enumerate(("Spy Walls", "Spy", "Spy Combo"), start=1):
            _register(svc, user_svc, arch_svc, tournament, tg_id, name)

        sectors = chart_svc.build_sectors(tournament.id)

        assert [(s.name, s.count) for s in sectors] == [("Spy Combo", 3)]
        assert sectors[0].color == PALETTE["BG"]

    def test_case_and_hyphen_duplicates_merge(self, chart_svc, svc, user_svc, arch_svc, tournament):
        """В проде «Rakdos Madness» и «Rakdos madness» — разные архетипы, но одна колода."""
        for tg_id, name in enumerate(("Rakdos Madness", "Rakdos madness"), start=1):
            _register(svc, user_svc, arch_svc, tournament, tg_id, name)

        sectors = chart_svc.build_sectors(tournament.id)

        assert [(s.name, s.count) for s in sectors] == [("Rakdos Madness", 2)]

    def test_tron_family_merges(self, chart_svc, svc, user_svc, arch_svc, tournament):
        for tg_id, name in enumerate(("Flicker Tron", "Altar tron", "Monster Tron"), start=1):
            _register(svc, user_svc, arch_svc, tournament, tg_id, name)

        assert [(s.name, s.count) for s in chart_svc.build_sectors(tournament.id)] == [("Tron", 3)]

    def test_empty_tournament_has_no_sectors(self, chart_svc, tournament):
        assert chart_svc.build_sectors(tournament.id) == []


class TestRender:
    def test_returns_png_of_expected_width(self, chart_svc, svc, user_svc, arch_svc, tournament):
        _register(svc, user_svc, arch_svc, tournament, 1, "Blue Terror")

        data, filename = chart_svc.render(tournament.id)
        image = Image.open(io.BytesIO(data))

        assert filename == f"meta_chart_{tournament.id}.png"
        assert image.format == "PNG"
        assert image.width == WIDTH

    def test_returns_none_without_decks(self, chart_svc, tournament):
        assert chart_svc.render(tournament.id) is None

    def test_height_grows_with_legend_rows(self):
        one_row = Image.open(io.BytesIO(render_sectors([ChartSector("A", 1, "#FFFFFF")])))
        many_rows = Image.open(io.BytesIO(render_sectors([ChartSector(f"Deck {i}", 1, "#FFFFFF") for i in range(9)])))

        assert many_rows.height > one_row.height

    def test_single_sector_renders(self):
        assert render_sectors([ChartSector("Solo", 1, "#3B7DD8")])

    def test_tiny_sector_is_still_drawn(self):
        """Одна колода на 250: сектор уже́ зазора — раньше он молча пропадал из бублика,
        оставаясь строкой в легенде."""
        drawn = []
        original = ImageDraw.ImageDraw.pieslice

        def spy(self, box, start, end, **kwargs):
            drawn.append((start, end))
            return original(self, box, start, end, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "pieslice", spy):
            render_sectors([ChartSector("Big", 249, "#FF0000"), ChartSector("Lonely", 1, "#00FF00")])

        assert len(drawn) == 2
        assert all(end > start for start, end in drawn)

    def test_long_deck_name_does_not_crash(self):
        assert render_sectors([ChartSector("Очень длинное название колоды " * 5, 1, "#3B7DD8")])
