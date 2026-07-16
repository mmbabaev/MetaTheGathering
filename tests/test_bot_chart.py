"""Tests for the shared chart builder (bot/chart.py)."""

import threading
from unittest.mock import MagicMock

from sqlalchemy.exc import OperationalError

from bot import chart as chart_mod
from bot.chart import build_chart, build_standings
from core import models
from core.schemas import TournamentCreate
from services.tournament import TournamentService


def _tournament_with_deck(db, user_svc, arch_svc):
    svc = TournamentService(db)
    t = svc.create_tournament(TournamentCreate(title="Pauper 13.07.2026", chat_id=100))
    user = user_svc.get_or_create(tg_id=1, first_name="Alice")
    svc.register_participant(
        tournament_id=t.id, user_id=user.id, archetype_id=arch_svc.get_or_create_by_name("Blue Terror").id
    )
    db.commit()
    return t


async def test_returns_png_and_sectors(db, user_svc, arch_svc):
    t = _tournament_with_deck(db, user_svc, arch_svc)

    chart = await build_chart(db, t.id)

    assert chart.png.startswith(b"\x89PNG")
    assert chart.filename == f"meta_chart_{t.id}.png"
    # секторы отдаются наружу, чтобы вызывающий не считал мету второй раз
    assert [(s.name, s.count) for s in chart.sectors] == [("Blue Terror", 1)]


async def test_returns_none_without_decks(db):
    t = TournamentService(db).create_tournament(TournamentCreate(title="Пусто", chat_id=1))
    assert await build_chart(db, t.id) is None


async def test_db_work_stays_on_the_caller_thread(db, user_svc, arch_svc, monkeypatch):
    """Сессию SQLAlchemy нельзя уносить в поток, а 180 мс рисования нельзя оставлять на loop."""
    t = _tournament_with_deck(db, user_svc, arch_svc)
    main_thread = threading.get_ident()
    seen = {}

    real_prepare, real_render = chart_mod.MetaChartService.prepare, chart_mod.render_sectors

    def spy_prepare(self, tournament_id):
        seen["prepare"] = threading.get_ident()
        return real_prepare(self, tournament_id)

    def spy_render(sectors, subtitle=""):
        seen["render"] = threading.get_ident()
        return real_render(sectors, subtitle)

    monkeypatch.setattr(chart_mod.MetaChartService, "prepare", spy_prepare)
    monkeypatch.setattr(chart_mod, "render_sectors", spy_render)

    await build_chart(db, t.id)

    assert seen["prepare"] == main_thread
    assert seen["render"] != main_thread


async def test_render_failure_returns_none(db, user_svc, arch_svc, monkeypatch):
    """График — украшение: его падение не должно ломать ни кнопку, ни анонс."""
    t = _tournament_with_deck(db, user_svc, arch_svc)
    monkeypatch.setattr(chart_mod, "render_sectors", MagicMock(side_effect=RuntimeError("шрифт не найден")))

    assert await build_chart(db, t.id) is None


async def test_db_failure_rolls_back_so_session_stays_usable(db, user_svc, arch_svc, monkeypatch):
    """После сбоя БД сессия должна остаться рабочей.

    prepare() пишет в БД (кэш цветов); без rollback отравленная сессия уронила бы
    следующий коммит вызывающего — например, флаг идемпотентности анонса.
    """
    t = _tournament_with_deck(db, user_svc, arch_svc)
    monkeypatch.setattr(
        chart_mod.MetaChartService,
        "prepare",
        MagicMock(side_effect=OperationalError("SELECT 1", {}, Exception("connection lost"))),
    )

    assert await build_chart(db, t.id) is None
    db.commit()  # не должно бросить PendingRollbackError


async def test_uses_injected_chart_service(db, user_svc, arch_svc):
    t = _tournament_with_deck(db, user_svc, arch_svc)
    svc = MagicMock()
    svc.prepare.return_value = None

    assert await build_chart(db, t.id, chart_svc=svc) is None
    svc.prepare.assert_called_once_with(t.id)


# ── build_standings — та же безопасная механика, что и build_chart ────────────


def _finished_tournament(db, user_svc, arch_svc):
    """Мини-турнир с одним сыгранным матчем, чтобы были стендинги."""
    svc = TournamentService(db)
    t = svc.create_tournament(TournamentCreate(title="Pauper 13.07.2026", chat_id=100, club="Edinorog"))
    user = user_svc.get_or_create(tg_id=1, first_name="Алиса", last_name="Кучина")
    svc.register_participant(
        tournament_id=t.id, user_id=user.id, archetype_id=arch_svc.get_or_create_by_name("Blue Terror").id
    )
    db.add(
        models.RoundPairing(
            tournament_id=t.id,
            round_number=1,
            player_name="Кучина Алиса",
            opponent_name="Opp",
            table_number=1,
            player_wins=2,
            opponent_wins=0,
        )
    )
    db.commit()
    return t


async def test_standings_returns_png(db, user_svc, arch_svc):
    t = _finished_tournament(db, user_svc, arch_svc)

    pages = await build_standings(db, t.id)

    assert len(pages) == 1
    assert pages[0].png.startswith(b"\x89PNG")
    assert pages[0].filename == f"standings_{t.id}_1.png"


async def test_standings_empty_without_pairings(db):
    t = TournamentService(db).create_tournament(TournamentCreate(title="Пусто", chat_id=1))
    assert await build_standings(db, t.id) == []


async def test_standings_db_failure_rolls_back(db, user_svc, arch_svc, monkeypatch):
    t = _finished_tournament(db, user_svc, arch_svc)
    monkeypatch.setattr(
        chart_mod.StandingsImageService,
        "prepare",
        MagicMock(side_effect=OperationalError("SELECT 1", {}, Exception("connection lost"))),
    )

    assert await build_standings(db, t.id) == []
    db.commit()  # сессия не отравлена


async def test_standings_db_work_stays_on_caller_thread(db, user_svc, arch_svc, monkeypatch):
    t = _finished_tournament(db, user_svc, arch_svc)
    main_thread = threading.get_ident()
    seen = {}
    real_prepare, real_render = chart_mod.StandingsImageService.prepare, chart_mod.render_standings_pages

    def spy_prepare(self, tid):
        seen["prepare"] = threading.get_ident()
        return real_prepare(self, tid)

    def spy_render(rows, subtitle=""):
        seen["render"] = threading.get_ident()
        return real_render(rows, subtitle)

    monkeypatch.setattr(chart_mod.StandingsImageService, "prepare", spy_prepare)
    monkeypatch.setattr(chart_mod, "render_standings_pages", spy_render)

    await build_standings(db, t.id)

    assert seen["prepare"] == main_thread
    assert seen["render"] != main_thread
