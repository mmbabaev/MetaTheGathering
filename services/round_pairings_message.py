"""Persistence for editable tournament-round messages in club chats."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core import models


class RoundPairingsMessageService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert(
        self, tournament_id: int, round_number: int, chat_id: int, message_id: int
    ) -> models.TournamentRoundPairingsMessage:
        row = self.db.execute(
            select(models.TournamentRoundPairingsMessage).where(
                models.TournamentRoundPairingsMessage.tournament_id == tournament_id,
                models.TournamentRoundPairingsMessage.round_number == round_number,
            )
        ).scalar_one_or_none()
        now = models.utc_now()
        if row is None:
            row = models.TournamentRoundPairingsMessage(
                tournament_id=tournament_id,
                round_number=round_number,
                created_at=now,
            )
            self.db.add(row)
        row.chat_id = chat_id
        row.message_id = message_id
        row.edit_disabled_at = None
        row.updated_at = now
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_active(self, tournament_id: int, round_number: int) -> models.TournamentRoundPairingsMessage | None:
        return self.db.execute(
            select(models.TournamentRoundPairingsMessage).where(
                models.TournamentRoundPairingsMessage.tournament_id == tournament_id,
                models.TournamentRoundPairingsMessage.round_number == round_number,
                models.TournamentRoundPairingsMessage.edit_disabled_at.is_(None),
            )
        ).scalar_one_or_none()

    def disable(self, row_id: int, message_id: int) -> bool:
        result = self.db.execute(
            update(models.TournamentRoundPairingsMessage)
            .where(
                models.TournamentRoundPairingsMessage.id == row_id,
                models.TournamentRoundPairingsMessage.message_id == message_id,
            )
            .values(edit_disabled_at=models.utc_now(), updated_at=models.utc_now())
        )
        self.db.commit()
        return bool(result.rowcount)
