"""DB lease, сериализующий расчёт и доставку ачивок одного турнира."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, insert, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core import models

LEASE_DURATION = timedelta(minutes=5)


def acquire_achievement_lease(
    db: Session,
    tournament_id: int,
    *,
    now: datetime | None = None,
) -> str | None:
    """Атомарно занять турнир; вернуть token или None, если его обрабатывает другой worker."""
    acquired_at = now or models.utc_now()
    token = uuid.uuid4().hex
    try:
        db.execute(
            insert(models.AchievementProcessingLease).values(
                tournament_id=tournament_id,
                token=token,
                locked_until=acquired_at + LEASE_DURATION,
                created_at=acquired_at,
                updated_at=acquired_at,
            )
        )
        db.commit()
        return token
    except IntegrityError:
        db.rollback()

    # Аварийно оставленный lease можно перехватить после expiry. Условный UPDATE
    # гарантирует, что из нескольких претендентов победит только один.
    claimed = db.execute(
        update(models.AchievementProcessingLease)
        .where(
            models.AchievementProcessingLease.tournament_id == tournament_id,
            models.AchievementProcessingLease.locked_until <= acquired_at,
        )
        .values(
            token=token,
            locked_until=acquired_at + LEASE_DURATION,
            updated_at=acquired_at,
        )
    )
    db.commit()
    return token if claimed.rowcount == 1 else None


def release_achievement_lease(db: Session, tournament_id: int, token: str) -> None:
    """Освободить только собственный lease; чужой token удалить не может."""
    db.rollback()  # очищает возможную failed transaction перед best-effort release
    db.execute(
        delete(models.AchievementProcessingLease).where(
            models.AchievementProcessingLease.tournament_id == tournament_id,
            models.AchievementProcessingLease.token == token,
        )
    )
    db.commit()
