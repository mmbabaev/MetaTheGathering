"""Storage and visibility rules for plain-text internal-Swiss decklists."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from core import models
from core.config import settings
from services import errors
from services.names import format_participant_name
from services.utils import get_tournament

MAX_DECKLIST_LENGTH = 3500


@dataclass(frozen=True)
class DecklistPlayer:
    participant_id: int
    name: str
    archetype: str
    has_decklist: bool


@dataclass(frozen=True)
class DecklistView(DecklistPlayer):
    raw_text: str | None


class DecklistService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _is_owner(tg_id: int) -> bool:
        return settings.OWNER_CHAT_ID is not None and tg_id == settings.OWNER_CHAT_ID

    def _participant(self, participant_id: int) -> models.Participant:
        participant = self.db.execute(
            select(models.Participant)
            .options(
                joinedload(models.Participant.user),
                joinedload(models.Participant.archetype),
                joinedload(models.Participant.decklist),
            )
            .where(models.Participant.id == participant_id)
        ).scalar_one_or_none()
        if participant is None:
            raise errors.ParticipantNotFound()
        return participant

    @staticmethod
    def _ensure_internal(tournament: models.Tournament) -> None:
        if tournament.engine_mode != models.TournamentEngineMode.INTERNAL_SWISS:
            raise errors.DecklistError("Деклисты доступны только во внутреннем Swiss.")

    def participant_for_user(self, tournament_id: int, tg_id: int) -> models.Participant | None:
        return self.db.execute(
            select(models.Participant)
            .join(models.User, models.User.id == models.Participant.user_id)
            .options(joinedload(models.Participant.decklist))
            .where(models.Participant.tournament_id == tournament_id, models.User.tg_id == tg_id)
        ).scalar_one_or_none()

    def save(self, tournament_id: int, tg_id: int, raw_text: str) -> DecklistView:
        tournament = get_tournament(self.db, tournament_id)
        self._ensure_internal(tournament)
        if tournament.status != models.TournamentStatus.REGISTRATION:
            raise errors.DecklistError("После начала турнира деклист нельзя изменить.")
        participant = self.participant_for_user(tournament_id, tg_id)
        if participant is None:
            raise errors.DecklistError("Сначала запишитесь на турнир.")
        if participant.archetype_id is None and not tournament.is_draft:
            raise errors.DecklistError("Сначала выберите архетип колоды.")
        text = raw_text.strip()
        if not text:
            raise errors.DecklistError("Деклист не может быть пустым.")
        if len(text) > MAX_DECKLIST_LENGTH:
            raise errors.DecklistError(f"Деклист слишком длинный: максимум {MAX_DECKLIST_LENGTH} символов.")
        now = models.utc_now()
        if participant.decklist is None:
            participant.decklist = models.ParticipantDecklist(raw_text=text, created_at=now, updated_at=now)
        else:
            participant.decklist.raw_text = text
            participant.decklist.updated_at = now
        self.db.commit()
        return self.view(participant.id, tg_id)

    def can_view_all(self, tournament: models.Tournament, tg_id: int) -> bool:
        return (
            tournament.status == models.TournamentStatus.CLOSED
            or tournament.created_by_tg_id == tg_id
            or self._is_owner(tg_id)
        )

    def list_players(self, tournament_id: int, tg_id: int) -> list[DecklistPlayer]:
        tournament = get_tournament(self.db, tournament_id)
        self._ensure_internal(tournament)
        if not self.can_view_all(tournament, tg_id):
            raise errors.DecklistError("Деклисты других игроков пока недоступны.")
        rows = (
            self.db.execute(
                select(models.Participant)
                .options(
                    joinedload(models.Participant.user),
                    joinedload(models.Participant.archetype),
                    joinedload(models.Participant.decklist),
                )
                .where(models.Participant.tournament_id == tournament_id)
                .order_by(
                    models.Participant.final_place.asc().nullslast(),
                    models.Participant.created_at,
                    models.Participant.id,
                )
            )
            .scalars()
            .all()
        )
        return [self._summary(row) for row in rows]

    def view(self, participant_id: int, tg_id: int) -> DecklistView:
        participant = self._participant(participant_id)
        tournament = participant.tournament
        self._ensure_internal(tournament)
        is_self = participant.user.tg_id == tg_id
        if not is_self and not self.can_view_all(tournament, tg_id):
            raise errors.DecklistError("Этот деклист пока недоступен.")
        summary = self._summary(participant)
        return DecklistView(
            **summary.__dict__, raw_text=participant.decklist.raw_text if participant.decklist else None
        )

    @staticmethod
    def _summary(participant: models.Participant) -> DecklistPlayer:
        name = format_participant_name(participant.user.first_name, participant.user.last_name)
        if not name:
            name = f"@{participant.user.username}" if participant.user.username else f"id{participant.id}"
        return DecklistPlayer(
            participant_id=participant.id,
            name=name,
            archetype=participant.archetype.name if participant.archetype else "архетип не указан",
            has_decklist=participant.decklist is not None,
        )
