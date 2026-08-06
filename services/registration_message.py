from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from core import models

HIDDEN_PARTICIPANT_COUNT = -1


def format_registration_message(base_text: str, participant_count: int) -> str:
    return f"{base_text.rstrip()}\n\nЗаписалось: {participant_count}"


class RegistrationMessageService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def participant_count(self, tournament_id: int) -> int:
        return self.db.scalar(
            select(func.count(models.Participant.id)).where(models.Participant.tournament_id == tournament_id)
        ) or 0

    def upsert_last(
        self,
        *,
        tournament_id: int,
        chat_id: int,
        message_id: int,
        base_text: str,
        button_url: str | None,
        participant_count: int,
    ) -> models.TournamentRegistrationMessage:
        row = self.db.execute(
            select(models.TournamentRegistrationMessage).where(
                models.TournamentRegistrationMessage.tournament_id == tournament_id,
                models.TournamentRegistrationMessage.chat_id == chat_id,
            )
        ).scalar_one_or_none()
        now = models.utc_now()
        if row is None:
            row = models.TournamentRegistrationMessage(
                tournament_id=tournament_id,
                chat_id=chat_id,
                created_at=now,
            )
            self.db.add(row)
        row.message_id = message_id
        row.base_text = base_text.rstrip()
        row.button_url = button_url
        row.rendered_participant_count = participant_count
        row.edit_disabled_at = None
        row.updated_at = now
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_stale_active(self) -> list[tuple[models.TournamentRegistrationMessage, int]]:
        return self._list_active(show_count=True)

    def list_counted_active(self) -> list[tuple[models.TournamentRegistrationMessage, int]]:
        """Active messages currently showing a counter and therefore needing it removed."""
        return self._list_active(show_count=False)

    def _list_active(self, *, show_count: bool) -> list[tuple[models.TournamentRegistrationMessage, int]]:
        counts = (
            select(
                models.Participant.tournament_id.label("tournament_id"),
                func.count(models.Participant.id).label("participant_count"),
            )
            .group_by(models.Participant.tournament_id)
            .subquery()
        )
        actual_count = func.coalesce(counts.c.participant_count, 0)
        extra_condition = (
            models.TournamentRegistrationMessage.rendered_participant_count != actual_count
            if show_count
            else models.TournamentRegistrationMessage.rendered_participant_count != HIDDEN_PARTICIPANT_COUNT
        )
        stmt = (
            select(models.TournamentRegistrationMessage, actual_count)
            .join(models.Tournament, models.Tournament.id == models.TournamentRegistrationMessage.tournament_id)
            .outerjoin(counts, counts.c.tournament_id == models.TournamentRegistrationMessage.tournament_id)
            .where(
                models.Tournament.status != models.TournamentStatus.CLOSED,
                models.TournamentRegistrationMessage.edit_disabled_at.is_(None),
                extra_condition,
            )
        )
        return [(row, int(count)) for row, count in self.db.execute(stmt).all()]

    def mark_rendered(self, row_id: int, message_id: int, participant_count: int) -> bool:
        result = self.db.execute(
            update(models.TournamentRegistrationMessage)
            .where(
                models.TournamentRegistrationMessage.id == row_id,
                models.TournamentRegistrationMessage.message_id == message_id,
            )
            .values(rendered_participant_count=participant_count, updated_at=models.utc_now())
        )
        self.db.commit()
        return bool(result.rowcount)

    def disable(self, row_id: int, message_id: int) -> bool:
        result = self.db.execute(
            update(models.TournamentRegistrationMessage)
            .where(
                models.TournamentRegistrationMessage.id == row_id,
                models.TournamentRegistrationMessage.message_id == message_id,
            )
            .values(edit_disabled_at=models.utc_now(), updated_at=models.utc_now())
        )
        self.db.commit()
        return bool(result.rowcount)
