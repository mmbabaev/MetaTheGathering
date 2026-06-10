"""Tests for AetherhubFinalReimportJob — morning re-import to backfill final scores."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from bot.scheduler import AetherhubFinalReimportJob
from core import models
from core.schemas import TournamentCreate
from services.aetherhub_models import AetherhubPairing, AetherhubRound, AetherhubTournamentData
from services.tournament import TournamentService

_URL = "https://aetherhub.com/Tourney/RoundTourney/99992"


def _tournament(db, *, url=_URL, created_days_ago=0):
    t = TournamentService(db).create_tournament(TournamentCreate(title="Pauper", chat_id=1))
    obj = db.get(models.Tournament, t.id)
    obj.aetherhub_url = url
    if created_days_ago:
        obj.created_at = datetime.utcnow() - timedelta(days=created_days_ago)
    db.commit()
    return obj


def _scored_data():
    return AetherhubTournamentData(
        url=_URL,
        players=[],
        rounds=[
            AetherhubRound(
                number=1,
                pairings=[
                    AetherhubPairing(player="Alice", opponent="Bob", table_number=1, player_wins=2, opponent_wins=1),
                    AetherhubPairing(player="Bob", opponent="Alice", table_number=1, player_wins=1, opponent_wins=2),
                ],
            )
        ],
    )


def _aetherhub_mock(data):
    svc = MagicMock()
    svc.fetch_tournament.return_value = data
    return svc


@pytest.fixture
def use_test_db(db, monkeypatch):
    """Make the job's internal SessionLocal() reuse the test session (no real close)."""
    monkeypatch.setattr("bot.scheduler.SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    return db


async def test_reimports_recent_and_populates_scores(db, use_test_db):
    t = _tournament(db)  # created now → within window
    db.add(
        models.RoundPairing(
            tournament_id=t.id, round_number=1, player_name="Alice", opponent_name="Bob", table_number=1
        )
    )
    db.add(
        models.RoundPairing(
            tournament_id=t.id, round_number=1, player_name="Bob", opponent_name="Alice", table_number=1
        )
    )
    db.commit()

    job = AetherhubFinalReimportJob(_aetherhub_mock(_scored_data()))
    await job.run(now=datetime.now(timezone.utc), db=db)

    db.expire_all()
    alice = db.query(models.RoundPairing).filter_by(tournament_id=t.id, player_name="Alice").first()
    assert (alice.player_wins, alice.opponent_wins) == (2, 1)


async def test_skips_tournaments_outside_window(db, use_test_db):
    _tournament(db, created_days_ago=5)  # too old → not re-imported
    mock = _aetherhub_mock(_scored_data())
    await AetherhubFinalReimportJob(mock).run(now=datetime.now(timezone.utc), db=db)
    mock.fetch_tournament.assert_not_called()


async def test_skips_tournaments_without_url(db, use_test_db):
    _tournament(db, url=None)
    mock = _aetherhub_mock(_scored_data())
    await AetherhubFinalReimportJob(mock).run(now=datetime.now(timezone.utc), db=db)
    mock.fetch_tournament.assert_not_called()


async def test_no_tournaments_no_fetch(db, use_test_db):
    mock = _aetherhub_mock(_scored_data())
    await AetherhubFinalReimportJob(mock).run(now=datetime.now(timezone.utc), db=db)
    mock.fetch_tournament.assert_not_called()


async def test_fetch_failure_does_not_raise(db, use_test_db):
    _tournament(db)
    mock = MagicMock()
    mock.fetch_tournament.side_effect = RuntimeError("network down")
    # must not raise — one bad tournament shouldn't abort the morning job
    await AetherhubFinalReimportJob(mock).run(now=datetime.now(timezone.utc), db=db)
