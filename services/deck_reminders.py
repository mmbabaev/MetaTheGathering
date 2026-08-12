"""Recipient selection and delivery state for deferred-deck reminders."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models


class DeckReminderStage(str, Enum):
    PRESTART = "prestart"
    ROUND2 = "round2"


@dataclass(frozen=True)
class DeckReminderRecipient:
    participant_id: int
    tg_id: int


class DeckReminderService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _sent_column(stage: DeckReminderStage):
        if stage == DeckReminderStage.PRESTART:
            return models.Participant.deck_reminder_prestart_sent_at
        return models.Participant.deck_reminder_round2_sent_at

    def pending_recipients(
        self, tournament_id: int, stage: DeckReminderStage
    ) -> list[DeckReminderRecipient]:
        """Real Telegram users who explicitly deferred this deck and still have none."""
        sent_column = self._sent_column(stage)
        rows = self.db.execute(
            select(models.Participant.id, models.User.tg_id)
            .join(models.User, models.User.id == models.Participant.user_id)
            .where(
                models.Participant.tournament_id == tournament_id,
                models.Participant.deck_deferred.is_(True),
                models.Participant.archetype_id.is_(None),
                sent_column.is_(None),
                models.User.tg_id > 0,
            )
            .order_by(models.Participant.id)
        ).all()
        return [DeckReminderRecipient(participant_id=row.id, tg_id=row.tg_id) for row in rows]

    def mark_sent(self, participant_ids: list[int], stage: DeckReminderStage) -> None:
        if not participant_ids:
            return
        sent_column = self._sent_column(stage)
        self.db.query(models.Participant).filter(
            models.Participant.id.in_(participant_ids),
            sent_column.is_(None),
        ).update({sent_column: models.utc_now()}, synchronize_session=False)
        self.db.commit()
