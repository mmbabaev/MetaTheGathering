"""Межпроцессная сериализация расчёта и owner-доставки ачивок."""

from datetime import timedelta

from sqlalchemy.orm import Session

from core import models
from services.achievement_processing_lease import acquire_achievement_lease, release_achievement_lease


def test_second_session_cannot_acquire_live_lease(db, tournament):
    other = Session(db.bind)
    try:
        token = acquire_achievement_lease(db, tournament.id)

        assert token is not None
        assert acquire_achievement_lease(other, tournament.id) is None
    finally:
        other.close()
        if token:
            release_achievement_lease(db, tournament.id, token)


def test_lease_can_be_acquired_after_release(db, tournament):
    first = acquire_achievement_lease(db, tournament.id)
    assert first is not None
    release_achievement_lease(db, tournament.id, first)

    second = acquire_achievement_lease(db, tournament.id)

    assert second is not None and second != first
    release_achievement_lease(db, tournament.id, second)


def test_wrong_token_does_not_release_lease(db, tournament):
    token = acquire_achievement_lease(db, tournament.id)
    assert token is not None

    release_achievement_lease(db, tournament.id, "not-the-owner-token")

    assert acquire_achievement_lease(db, tournament.id) is None
    release_achievement_lease(db, tournament.id, token)


def test_expired_lease_is_atomically_taken_over(db, tournament):
    first = acquire_achievement_lease(db, tournament.id)
    assert first is not None
    lease = db.get(models.AchievementProcessingLease, tournament.id)
    lease.locked_until = models.utc_now() - timedelta(seconds=1)
    db.commit()

    second = acquire_achievement_lease(db, tournament.id)

    assert second is not None and second != first
    assert db.get(models.AchievementProcessingLease, tournament.id).token == second
    release_achievement_lease(db, tournament.id, second)
