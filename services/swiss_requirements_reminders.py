"""Due recipients for the one-off internal-Swiss pre-start reminder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from core import models


@dataclass(frozen=True)
class SwissRequirementsRecipient:
    participant_id: int
    tournament_id: int
    tg_id: int
    missing_archetype: bool
    missing_decklist: bool


class SwissRequirementsReminderService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _naive_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def pending(self, now: datetime, *, horizon: timedelta = timedelta(minutes=15)) -> list[SwissRequirementsRecipient]:
        now = self._naive_utc(now)
        deadline = now + horizon
        rows = self.db.execute(
            select(
                models.Participant.id,
                models.Participant.tournament_id,
                models.User.tg_id,
                models.Participant.archetype_id,
                models.ParticipantDecklist.id.label("decklist_id"),
            )
            .join(models.Tournament, models.Tournament.id == models.Participant.tournament_id)
            .join(models.User, models.User.id == models.Participant.user_id)
            .outerjoin(
                models.ParticipantDecklist,
                models.ParticipantDecklist.participant_id == models.Participant.id,
            )
            .where(
                models.Tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS,
                models.Tournament.is_draft.is_(False),
                models.Tournament.status == models.TournamentStatus.REGISTRATION,
                models.Tournament.decklist_reminders_enabled.is_(True),
                models.Tournament.registration_close_at > now,
                models.Tournament.registration_close_at <= deadline,
                models.Participant.swiss_requirements_reminder_sent_at.is_(None),
                models.User.tg_id > 0,
                or_(
                    models.Participant.archetype_id.is_(None),
                    models.ParticipantDecklist.id.is_(None),
                ),
            )
            .order_by(models.Tournament.registration_close_at, models.Participant.id)
        ).all()
        return [
            SwissRequirementsRecipient(
                participant_id=row.id,
                tournament_id=row.tournament_id,
                tg_id=row.tg_id,
                missing_archetype=row.archetype_id is None,
                missing_decklist=row.decklist_id is None,
            )
            for row in rows
        ]

    def mark_sent(self, participant_ids: list[int]) -> None:
        if not participant_ids:
            return
        self.db.query(models.Participant).filter(
            models.Participant.id.in_(participant_ids),
            models.Participant.swiss_requirements_reminder_sent_at.is_(None),
        ).update(
            {models.Participant.swiss_requirements_reminder_sent_at: models.utc_now()},
            synchronize_session=False,
        )
        self.db.commit()
