"""Transactional outbox для текстовых owner-отчётов ачивок."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models

RECIPIENT_OWNER = "owner"
STATUS_PENDING = "pending"
STATUS_SENT = "sent"


def create_owner_deliveries(
    db: Session,
    tournament_id: int,
    chat_id: int | None,
    messages: Sequence[str],
) -> list[models.AchievementReportDelivery]:
    """Добавить один атомарный report batch в текущую транзакцию без commit."""
    report_id = uuid.uuid4().hex
    deliveries = [
        models.AchievementReportDelivery(
            report_id=report_id,
            tournament_id=tournament_id,
            recipient_type=RECIPIENT_OWNER,
            chat_id=chat_id,
            message_index=index,
            payload=message,
            status=STATUS_PENDING,
        )
        for index, message in enumerate(messages)
    ]
    db.add_all(deliveries)
    return deliveries


def pending_owner_deliveries(db: Session, tournament_id: int) -> list[models.AchievementReportDelivery]:
    """Все недоставленные части отчётов турнира в стабильном порядке."""
    return list(
        db.execute(
            select(models.AchievementReportDelivery)
            .where(
                models.AchievementReportDelivery.tournament_id == tournament_id,
                models.AchievementReportDelivery.recipient_type == RECIPIENT_OWNER,
                models.AchievementReportDelivery.status == STATUS_PENDING,
            )
            .order_by(
                models.AchievementReportDelivery.created_at,
                models.AchievementReportDelivery.report_id,
                models.AchievementReportDelivery.message_index,
            )
        )
        .scalars()
        .all()
    )
