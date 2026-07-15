"""Tests for the metagame donut chart (services/meta_chart.py)."""

import io
from unittest.mock import MagicMock

import pytest
from PIL import Image

from services.archetype import ArchetypeService
from services.deck_colors import PALETTE, DeckColorResolver
from services.meta_chart import WIDTH, ChartSector, MetaChartService, plural_decks, render_sectors


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
        _register(svc, user_svc, arch_svc, tournament, 1, "Gates")

        assert chart_svc.build_sectors(tournament.id)[0].color == PALETTE[""]

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

    def test_long_deck_name_does_not_crash(self):
        assert render_sectors([ChartSector("Очень длинное название колоды " * 5, 1, "#3B7DD8")])
