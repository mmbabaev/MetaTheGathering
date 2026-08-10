"""Universal transactional outbox for owner and targeted player deliveries."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models

RECIPIENT_OWNER = "owner"
RECIPIENT_PLAYER = "player"
PAYLOAD_ACHIEVEMENT_REPORT = "achievement_report"
STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_CANCELLED = "cancelled"


def create_owner_deliveries(
    db: Session,
    tournament_id: int,
    chat_id: int | None,
    messages: Sequence[str],
    *,
    processing_run_id: int | None = None,
) -> list[models.AchievementReportDelivery]:
    """Add one atomic owner batch to the current transaction."""
    report_id = uuid.uuid4().hex
    return _create_batch(
        db,
        report_id=report_id,
        tournament_id=tournament_id,
        recipient_type=RECIPIENT_OWNER,
        user_id=None,
        chat_id=chat_id,
        payload_type=PAYLOAD_ACHIEVEMENT_REPORT,
        payload_version=1,
        messages=messages,
        key_prefix=f"owner:t{tournament_id}:run{processing_run_id or report_id}",
    )


def create_player_deliveries(
    db: Session,
    tournament_id: int,
    recipients: Mapping[int, tuple[int, Sequence[str]]],
    *,
    processing_run_id: int,
) -> list[models.AchievementReportDelivery]:
    """Queue separate per-player batches; every row has one concrete recipient."""
    created: list[models.AchievementReportDelivery] = []
    for user_id, (chat_id, messages) in sorted(recipients.items()):
        created.extend(
            _create_batch(
                db,
                report_id=uuid.uuid4().hex,
                tournament_id=tournament_id,
                recipient_type=RECIPIENT_PLAYER,
                user_id=user_id,
                chat_id=chat_id,
                payload_type=PAYLOAD_ACHIEVEMENT_REPORT,
                payload_version=1,
                messages=messages,
                key_prefix=f"player:t{tournament_id}:run{processing_run_id}:u{user_id}",
            )
        )
    return created


def create_targeted_player_delivery(
    db: Session,
    *,
    tournament_id: int,
    user_id: int,
    chat_id: int,
    payload_type: str,
    payload_version: int,
    payload: str,
    idempotency_key: str,
) -> models.AchievementReportDelivery:
    """Extension point for confirmation/claim payloads: exactly one player, never fan-out."""
    existing = db.execute(
        select(models.AchievementReportDelivery).where(
            models.AchievementReportDelivery.idempotency_key == idempotency_key
        )
    ).scalar_one_or_none()
    if existing is not None:
        expected = (
            tournament_id,
            user_id,
            chat_id,
            payload_type,
            payload_version,
            payload,
        )
        actual = (
            existing.tournament_id,
            existing.user_id,
            existing.chat_id,
            existing.payload_type,
            existing.payload_version,
            existing.payload,
        )
        if actual != expected:
            raise ValueError("idempotency key is already bound to another targeted payload")
        return existing
    delivery = models.AchievementReportDelivery(
        report_id=uuid.uuid4().hex,
        tournament_id=tournament_id,
        recipient_type=RECIPIENT_PLAYER,
        user_id=user_id,
        chat_id=chat_id,
        message_index=0,
        payload_type=payload_type,
        payload_version=payload_version,
        payload=payload,
        idempotency_key=idempotency_key,
        status=STATUS_PENDING,
    )
    db.add(delivery)
    return delivery


def _create_batch(
    db: Session,
    *,
    report_id: str,
    tournament_id: int,
    recipient_type: str,
    user_id: int | None,
    chat_id: int | None,
    payload_type: str,
    payload_version: int,
    messages: Sequence[str],
    key_prefix: str,
) -> list[models.AchievementReportDelivery]:
    deliveries = [
        models.AchievementReportDelivery(
            report_id=report_id,
            tournament_id=tournament_id,
            recipient_type=recipient_type,
            user_id=user_id,
            chat_id=chat_id,
            message_index=index,
            payload_type=payload_type,
            payload_version=payload_version,
            payload=message,
            idempotency_key=f"{key_prefix}:i{index}",
            status=STATUS_PENDING,
        )
        for index, message in enumerate(messages)
    ]
    db.add_all(deliveries)
    return deliveries


def pending_deliveries(
    db: Session,
    tournament_id: int,
    *,
    recipient_type: str | None = None,
    limit: int | None = None,
) -> list[models.AchievementReportDelivery]:
    stmt = (
        select(models.AchievementReportDelivery)
        .where(
            models.AchievementReportDelivery.tournament_id == tournament_id,
            models.AchievementReportDelivery.status == STATUS_PENDING,
        )
        .order_by(
            models.AchievementReportDelivery.created_at,
            models.AchievementReportDelivery.report_id,
            models.AchievementReportDelivery.message_index,
        )
    )
    if recipient_type is not None:
        stmt = stmt.where(models.AchievementReportDelivery.recipient_type == recipient_type)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars().all())


def pending_owner_deliveries(db: Session, tournament_id: int) -> list[models.AchievementReportDelivery]:
    return pending_deliveries(db, tournament_id, recipient_type=RECIPIENT_OWNER)
