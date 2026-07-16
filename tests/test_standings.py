"""Tests for tournament standings: data (StandingRow / get_standings) and image."""

import io

import pytest
from PIL import Image

from core import models
from core.schemas import TournamentCreate
from services.aetherhub_import_service import AetherhubImportService, StandingRow
from services.chart_style import WIDTH
from services.standings_image import (
    PAGE_SIZE,
    StandingsImageService,
    accent_color,
    render_standings,
    render_standings_pages,
)


class TestStandingRow:
    @pytest.mark.parametrize(
        "w,loss,d,points,record",
        [
            (4, 0, 0, 12, "4-0"),
            (3, 0, 1, 10, "3-0-1"),
            (3, 1, 0, 9, "3-1"),
            (2, 1, 1, 7, "2-1-1"),
            (0, 4, 0, 0, "0-4"),
        ],
    )
    def test_points_and_record(self, w, loss, d, points, record):
        row = StandingRow(place=1, display_name="X", archetype_name=None, wins=w, losses=loss, draws=d)
        assert row.points == points
        assert row.record == record


class TestAccentColor:
    def test_undefeated_is_green(self):
        assert accent_color(12) == (0x54, 0xB8, 0x6A)

    def test_no_loss_with_draw(self):
        assert accent_color(10) is not None

    def test_one_loss(self):
        assert accent_color(9) is not None

    def test_below_nine_has_no_accent(self):
        assert accent_color(8) is None
        assert accent_color(0) is None

    def test_tiers_are_distinct(self):
        assert len({accent_color(12), accent_color(10), accent_color(9)}) == 3


# ── get_standings ────────────────────────────────────────────────────────────


def _pairing(db, t_id, rnd, player, opponent, pw, ow):
    db.add(
        models.RoundPairing(
            tournament_id=t_id,
            round_number=rnd,
            player_name=player,
            opponent_name=opponent,
            table_number=1,
            player_wins=pw,
            opponent_wins=ow,
        )
    )


def _four_round_tournament(db, svc, user_svc, arch_svc):
    """Alice 4-0, Bob 3-0-1 (draw), Carol 3-1, Dave 0-4. Alice & Bob registered with decks."""
    t = svc.create_tournament(TournamentCreate(title="Pauper 13.07.2026", chat_id=100, club="Edinorog"))
    burn = arch_svc.get_or_create_by_name("Burn")
    elves = arch_svc.get_or_create_by_name("Elves")

    alice = user_svc.get_or_create(tg_id=1, first_name="Алиса", last_name="Кучина")
    bob = user_svc.get_or_create(tg_id=2, first_name="Боб", last_name="Володин")
    svc.register_participant(tournament_id=t.id, user_id=alice.id, archetype_id=burn.id)
    svc.register_participant(tournament_id=t.id, user_id=bob.id, archetype_id=elves.id)

    for r in (1, 2, 3, 4):
        _pairing(db, t.id, r, "Кучина Алиса", "Opp", 2, 0)  # Alice 4-0
    for r in (1, 2, 3):
        _pairing(db, t.id, r, "Володин Боб", "Opp", 2, 0)
    _pairing(db, t.id, 4, "Володин Боб", "Opp", 1, 1)  # Bob 3-0-1
    for r in (1, 2, 3):
        _pairing(db, t.id, r, "Carol Unregistered", "Opp", 2, 0)
    _pairing(db, t.id, 4, "Carol Unregistered", "Opp", 0, 2)  # Carol 3-1, not in bot
    for r in (1, 2, 3, 4):
        _pairing(db, t.id, r, "Dave Loser", "Opp", 0, 2)  # Dave 0-4
    db.commit()
    return t


class TestGetStandings:
    def test_all_players_ordered_by_points(self, db, svc, user_svc, arch_svc):
        t = _four_round_tournament(db, svc, user_svc, arch_svc)

        rows = AetherhubImportService(db).get_standings(t.id)

        assert [r.place for r in rows] == [1, 2, 3, 4]
        assert [r.points for r in rows] == [12, 10, 9, 0]

    def test_registered_players_show_name_and_deck(self, db, svc, user_svc, arch_svc):
        t = _four_round_tournament(db, svc, user_svc, arch_svc)

        rows = AetherhubImportService(db).get_standings(t.id)
        top = rows[0]

        assert top.display_name == "Кучина Алиса"  # Фамилия Имя
        assert top.archetype_name == "Burn"

    def test_unregistered_player_keeps_pairing_name_and_no_deck(self, db, svc, user_svc, arch_svc):
        t = _four_round_tournament(db, svc, user_svc, arch_svc)

        carol = next(r for r in AetherhubImportService(db).get_standings(t.id) if r.points == 9)

        assert carol.display_name == "Carol Unregistered"
        assert carol.archetype_name is None

    def test_empty_without_pairings(self, db, svc):
        t = svc.create_tournament(TournamentCreate(title="Empty", chat_id=1))
        assert AetherhubImportService(db).get_standings(t.id) == []


# ── image ────────────────────────────────────────────────────────────────────


class TestRenderStandings:
    def test_produces_png_of_expected_width(self):
        rows = [StandingRow(1, "Alice", "Burn", 4, 0, 0)]
        image = Image.open(io.BytesIO(render_standings(rows, "Единорог · 13.07.2026")))
        assert image.format == "PNG"
        assert image.width == WIDTH

    def test_height_grows_with_rows(self):
        one = Image.open(io.BytesIO(render_standings([StandingRow(1, "A", None, 1, 0, 0)])))
        many = Image.open(io.BytesIO(render_standings([StandingRow(i, f"P{i}", None, 1, 0, 0) for i in range(1, 21)])))
        assert many.height > one.height

    def test_emoji_in_deck_name_does_not_crash(self):
        rows = [StandingRow(1, "Alice", "🟢🔵🐸 Bogles", 4, 0, 0, color_identity="UG")]
        assert render_standings(rows).startswith(b"\x89PNG")

    def test_long_name_and_deck_do_not_crash(self):
        rows = [StandingRow(1, "Оченьдлиннаяфамилия Оченьдлинноеимя", "Очень длинное название" * 3, 3, 1, 0)]
        assert render_standings(rows).startswith(b"\x89PNG")

    def test_all_mana_colors_render(self):
        rows = [StandingRow(1, "Alice", "5c", 4, 0, 0, color_identity="WUBRG")]
        assert render_standings(rows).startswith(b"\x89PNG")


class TestPaging:
    def test_one_page_up_to_page_size(self):
        rows = [StandingRow(i, f"P{i}", None, 1, 0, 0) for i in range(1, PAGE_SIZE + 1)]
        assert len(render_standings_pages(rows)) == 1

    def test_splits_into_pages_of_thirty(self):
        rows = [StandingRow(i, f"P{i}", None, 1, 0, 0) for i in range(1, 46)]
        pages = render_standings_pages(rows)
        assert len(pages) == 2  # 30 + 15
        assert all(p.startswith(b"\x89PNG") for p in pages)

    def test_render_returns_first_page(self):
        rows = [StandingRow(i, f"P{i}", None, 1, 0, 0) for i in range(1, 46)]
        assert render_standings(rows) == render_standings_pages(rows)[0]


class TestStandingsImageService:
    def test_render_returns_pages_with_filenames(self, db, svc, user_svc, arch_svc):
        t = _four_round_tournament(db, svc, user_svc, arch_svc)

        pages = StandingsImageService(db).render(t.id)

        assert len(pages) == 1  # 4 игрока — одна страница
        png, filename = pages[0]
        assert png.startswith(b"\x89PNG")
        assert filename == f"standings_{t.id}_1.png"

    def test_prepare_resolves_pips_and_render_needs_no_db(self, db, svc, user_svc, arch_svc):
        """prepare() — вся работа с БД (включая пипы по имени колоды); render рисует без сессии."""
        t = _four_round_tournament(db, svc, user_svc, arch_svc)
        data = StandingsImageService(db).prepare(t.id)

        db.close()

        assert data.subtitle == "Единорог · 13.07.2026"
        # Elves → зелёная колода (справочник), пип G проставлен на этапе prepare
        elves_row = next(r for r in data.rows if r.archetype_name == "Elves")
        assert elves_row.color_identity == "G"
        assert render_standings(data.rows, data.subtitle).startswith(b"\x89PNG")

    def test_returns_none_without_standings(self, db, svc):
        t = svc.create_tournament(TournamentCreate(title="Empty", chat_id=1))
        assert StandingsImageService(db).render(t.id) is None
