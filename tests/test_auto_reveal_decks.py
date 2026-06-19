"""Tests for AutoRevealDecksJob — reveal decks of today's active tournaments at 22:00 (#112)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.messages import format_decks_revealed
from bot.scheduler import AutoRevealDecksJob
from core import models
from core.schemas import TournamentCreate
from services.tournament import TournamentService

NOW = datetime(2026, 6, 17, 22, 0, tzinfo=timezone.utc)


def _tournament(db, chat_id, *, hidden=True, status=models.TournamentStatus.REGISTRATION, created_days_ago=0):
    t = TournamentService(db).create_tournament(TournamentCreate(title="T", chat_id=chat_id))
    obj = db.get(models.Tournament, t.id)
    obj.decks_hidden = hidden
    obj.status = status
    # Anchor created_at to the simulated NOW, not the wall clock — otherwise at certain
    # date boundaries "N days ago" collides with NOW's day and the test flakes (it did).
    obj.created_at = NOW.replace(tzinfo=None) - timedelta(days=created_days_ago)
    db.commit()
    return obj


async def test_reveals_hidden_decks_of_today(db):
    t = _tournament(db, chat_id=1, hidden=True)
    await AutoRevealDecksJob().run(now=NOW, db=db)
    db.refresh(t)
    assert t.decks_hidden is False


async def test_skips_closed_tournament(db):
    t = _tournament(db, chat_id=2, hidden=True, status=models.TournamentStatus.CLOSED)
    await AutoRevealDecksJob().run(now=NOW, db=db)
    db.refresh(t)
    assert t.decks_hidden is True  # CLOSED — не трогаем


async def test_skips_previous_day(db):
    t = _tournament(db, chat_id=3, hidden=True, created_days_ago=2)
    await AutoRevealDecksJob().run(now=NOW, db=db)
    db.refresh(t)
    assert t.decks_hidden is True  # создан не сегодня — не трогаем


async def test_already_revealed_stays_revealed(db):
    t = _tournament(db, chat_id=4, hidden=False)
    await AutoRevealDecksJob().run(now=NOW, db=db)
    db.refresh(t)
    assert t.decks_hidden is False


async def test_no_tournaments_no_error(db):
    await AutoRevealDecksJob().run(now=NOW, db=db)  # пустая база — без ошибок


def test_format_decks_revealed():
    rows = [
        SimpleNamespace(archetype_name="Red Madness", count=5),
        SimpleNamespace(archetype_name="Izzet Terror", count=3),
    ]
    text = format_decks_revealed("Edinorog", 10, 8, rows)
    assert "👁 Колоды раскрыты — Edinorog" in text
    assert "Участников: 10 (8 с колодой)" in text
    assert "1. Red Madness — 5" in text
    assert "2. Izzet Terror — 3" in text


async def test_announces_short_stats_to_chat(db, user_svc, arch_svc):
    t = _tournament(db, chat_id=555, hidden=True)
    burn = arch_svc.get_or_create_by_name("Burn")
    svc = TournamentService(db)
    for i in range(3):
        u = user_svc.get_or_create(tg_id=100 + i, first_name=f"P{i}")
        svc.register_participant(tournament_id=t.id, user_id=u.id, archetype_id=burn.id)

    bot = AsyncMock()
    await AutoRevealDecksJob().run(now=NOW, db=db, bot=bot)

    db.refresh(t)
    assert t.decks_hidden is False
    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == 555
    assert "Burn — 3" in kwargs["text"]
    assert "Колоды раскрыты" in kwargs["text"]


async def test_no_announce_without_bot(db):
    t = _tournament(db, chat_id=556, hidden=True)
    await AutoRevealDecksJob().run(now=NOW, db=db)  # без bot — только снятие флага
    db.refresh(t)
    assert t.decks_hidden is False
