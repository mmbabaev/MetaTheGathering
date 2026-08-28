"""Persistence for the editable meta-police group message."""

from __future__ import annotations

import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core import models


class MetaPoliceMessageService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert(
        self,
        *,
        tournament_id: int,
        chat_id: int,
        message_id: int,
        participant_ids: list[int],
        button_url: str | None,
    ) -> models.TournamentMissingDecksReminder:
        row = self.db.execute(
            select(models.TournamentMissingDecksReminder).where(
                models.TournamentMissingDecksReminder.tournament_id == tournament_id
            )
        ).scalar_one_or_none()
        now = models.utc_now()
        if row is None:
            row = models.TournamentMissingDecksReminder(
                tournament_id=tournament_id,
                created_at=now,
            )
            self.db.add(row)
        row.chat_id = chat_id
        row.message_id = message_id
        row.participant_ids_json = json.dumps(participant_ids)
        row.button_url = button_url
        row.edit_disabled_at = None
        row.updated_at = now
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_active(self, tournament_id: int) -> models.TournamentMissingDecksReminder | None:
        return self.db.execute(
            select(models.TournamentMissingDecksReminder).where(
                models.TournamentMissingDecksReminder.tournament_id == tournament_id,
                models.TournamentMissingDecksReminder.edit_disabled_at.is_(None),
            )
        ).scalar_one_or_none()

    def tracked_participants(self, row: models.TournamentMissingDecksReminder) -> list[models.Participant]:
        try:
            participant_ids = [int(value) for value in json.loads(row.participant_ids_json)]
        except (TypeError, ValueError, json.JSONDecodeError):
            participant_ids = []
        current_missing_ids = list(
            self.db.execute(
                select(models.Participant.id)
                .where(
                    models.Participant.tournament_id == row.tournament_id,
                    models.Participant.archetype_id.is_(None),
                )
                .order_by(models.Participant.created_at, models.Participant.id)
            ).scalars()
        )
        known_ids = set(participant_ids)
        new_ids = [participant_id for participant_id in current_missing_ids if participant_id not in known_ids]
        if new_ids:
            participant_ids.extend(new_ids)
            row.participant_ids_json = json.dumps(participant_ids)
            row.updated_at = models.utc_now()
            self.db.commit()
        if not participant_ids:
            return []
        participants = (
            self.db.execute(
                select(models.Participant).where(
                    models.Participant.tournament_id == row.tournament_id,
                    models.Participant.id.in_(participant_ids),
                )
            )
            .scalars()
            .all()
        )
        by_id = {participant.id: participant for participant in participants}
        return [by_id[participant_id] for participant_id in participant_ids if participant_id in by_id]

    def disable(self, row_id: int, message_id: int) -> bool:
        result = self.db.execute(
            update(models.TournamentMissingDecksReminder)
            .where(
                models.TournamentMissingDecksReminder.id == row_id,
                models.TournamentMissingDecksReminder.message_id == message_id,
            )
            .values(edit_disabled_at=models.utc_now(), updated_at=models.utc_now())
        )
        self.db.commit()
        return bool(result.rowcount)
