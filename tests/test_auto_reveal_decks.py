"""Tests for AutoRevealDecksJob — reveal decks of today's active tournaments at 22:00 (#112)."""

from datetime import datetime, timedelta, timezone

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
    if created_days_ago:
        obj.created_at = datetime.utcnow() - timedelta(days=created_days_ago)
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
