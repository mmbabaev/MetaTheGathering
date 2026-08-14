from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from core import models
from core.schemas import (
    ParticipantRead,
    ParticipantWithUserAndArchetype,
    TournamentCreate,
    TournamentRead,
    VoteRead,
)
from services import errors
from services.utils import ensure_tournament_status, get_tournament

# доменные настройки
CONFIRM_THRESHOLD = 3  # up - down >= 3 → confirmed = True
REJECT_THRESHOLD = 3  # down - up >= 3 → confirmed = False
CHANGE_VOTE_COOLDOWN = timedelta(seconds=30)


@dataclass
class DeckRecorder:
    """Метаписец: кто и сколько колод записал в турнире."""

    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    count: int


class TournamentService:
    """
    Сервисный слой для:
    - управления турнирами,
    - регистрации участников,
    - голосования и метагейма.
    """

    def __init__(self, db: Session):
        self.db = db

    # ===== private helpers =====

    def _get_participant(self, participant_id: int) -> models.Participant:
        participant = self.db.get(models.Participant, participant_id)
        if not participant:
            raise errors.ParticipantNotFound(f"Participant {participant_id} not found")
        return participant

    def _get_vote(
        self,
        *,
        tournament_id: int,
        participant_id: int,
        voter_id: int,
    ) -> Optional[models.Vote]:
        stmt = select(models.Vote).where(
            models.Vote.tournament_id == tournament_id,
            models.Vote.participant_id == participant_id,
            models.Vote.voter_id == voter_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def _recalculate_confirmation(self, participant: models.Participant) -> None:
        up = participant.upvotes_count
        down = participant.downvotes_count

        if up - down >= CONFIRM_THRESHOLD:
            participant.confirmed = True
        elif down - up >= REJECT_THRESHOLD:
            participant.confirmed = False
        # зона неопределённости — не меняем confirmed

    # ===== tournaments =====

    def create_tournament(self, data: TournamentCreate) -> TournamentRead:
        # один активный турнир на чат
        stmt = (
            select(models.Tournament)
            .where(
                models.Tournament.chat_id == data.chat_id,
                models.Tournament.status != models.TournamentStatus.CLOSED,
            )
            .limit(1)
        )
        active = self.db.execute(stmt).scalar_one_or_none()
        if active:
            raise errors.TournamentAlreadyExists(f"Chat {data.chat_id} already has active tournament #{active.id}")

        tournament = models.Tournament(
            title=data.title,
            chat_id=data.chat_id,
            slug=data.slug,
            club=data.club,
            status=models.TournamentStatus.REGISTRATION,
            registration_close_at=data.registration_close_at,
            created_at=models.utc_now(),
        )
        self.db.add(tournament)
        self.db.commit()
        self.db.refresh(tournament)
        return TournamentRead.model_validate(tournament)

    def get_active_tournament_for_chat(self, chat_id: int) -> Optional[TournamentRead]:
        stmt = (
            select(models.Tournament)
            .where(
                models.Tournament.chat_id == chat_id,
                models.Tournament.status != models.TournamentStatus.CLOSED,
            )
            .order_by(models.Tournament.created_at.desc())
            .limit(1)
        )
        obj = self.db.execute(stmt).scalar_one_or_none()
        return TournamentRead.model_validate(obj) if obj else None

    def list_tournaments_for_chat(
        self,
        chat_id: int,
        limit: int = 20,
        offset: int = 0,
    ) -> List[TournamentRead]:
        stmt = (
            select(models.Tournament)
            .where(models.Tournament.chat_id == chat_id)
            .order_by(models.Tournament.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = self.db.execute(stmt).scalars().all()
        return [TournamentRead.model_validate(t) for t in rows]

    def list_active_tournaments_for_chat(self, chat_id: int) -> List[TournamentRead]:
        """Турниры чата со статусом не CLOSED, по убыванию created_at."""
        stmt = (
            select(models.Tournament)
            .where(
                models.Tournament.chat_id == chat_id,
                models.Tournament.status != models.TournamentStatus.CLOSED,
            )
            .order_by(models.Tournament.created_at.desc())
        )
        rows = self.db.execute(stmt).scalars().all()
        return [TournamentRead.model_validate(t) for t in rows]

    def get_single_active_tournament(self) -> TournamentRead:
        """Возвращает единственный активный турнир.
        Raises TournamentNotFound если нет активных.
        Raises MultipleActiveTournaments если их несколько."""
        tournaments = self.list_all_active_tournaments()
        if not tournaments:
            raise errors.TournamentNotFound("No active tournaments")
        if len(tournaments) > 1:
            raise errors.MultipleActiveTournaments([(t.id, t.title) for t in tournaments])
        return tournaments[0]

    def list_all_active_tournaments(self) -> List[TournamentRead]:
        """Все турниры со статусом не CLOSED, по убыванию created_at."""
        stmt = (
            select(models.Tournament)
            .where(models.Tournament.status != models.TournamentStatus.CLOSED)
            .order_by(models.Tournament.created_at.desc())
        )
        rows = self.db.execute(stmt).scalars().all()
        return [TournamentRead.model_validate(t) for t in rows]

    def list_closed_tournaments(self, limit: int = 20) -> List[TournamentRead]:
        """Закрытые турниры, по убыванию created_at."""
        stmt = (
            select(models.Tournament)
            .where(models.Tournament.status == models.TournamentStatus.CLOSED)
            .order_by(models.Tournament.created_at.desc())
            .limit(limit)
        )
        rows = self.db.execute(stmt).scalars().all()
        return [TournamentRead.model_validate(t) for t in rows]

    def set_aetherhub_url(self, tournament_id: int, url: str) -> None:
        self.db.execute(
            update(models.Tournament).where(models.Tournament.id == tournament_id).values(aetherhub_url=url)
        )
        self.db.commit()

    def set_import_time(self, tournament_id: int, time_str: str | None) -> None:
        self.db.execute(
            update(models.Tournament)
            .where(models.Tournament.id == tournament_id)
            .values(aetherhub_import_time=time_str)
        )
        self.db.commit()

    def set_decks_hidden(self, tournament_id: int, hidden: bool) -> TournamentRead:
        tournament = get_tournament(self.db, tournament_id)
        tournament.decks_hidden = hidden
        self.db.commit()
        self.db.refresh(tournament)
        return TournamentRead.model_validate(tournament)

    def open_registration(self, tournament_id: int) -> TournamentRead:
        tournament = get_tournament(self.db, tournament_id)
        tournament.status = models.TournamentStatus.REGISTRATION
        tournament.registration_open_at = models.utc_now()

        self.db.commit()
        self.db.refresh(tournament)
        return TournamentRead.model_validate(tournament)

    def start_tournament(self, tournament_id: int) -> TournamentRead:
        tournament = get_tournament(self.db, tournament_id)
        ensure_tournament_status(
            tournament,
            allowed=[models.TournamentStatus.REGISTRATION],
        )

        tournament.status = models.TournamentStatus.ONGOING
        if not tournament.started_at:
            tournament.started_at = models.utc_now()

        self.db.commit()
        self.db.refresh(tournament)
        return TournamentRead.model_validate(tournament)

    def close_tournament(self, tournament_id: int) -> TournamentRead:
        tournament = get_tournament(self.db, tournament_id)
        ensure_tournament_status(
            tournament,
            allowed=[
                models.TournamentStatus.REGISTRATION,
                models.TournamentStatus.ONGOING,
            ],
        )

        tournament.status = models.TournamentStatus.CLOSED
        tournament.ended_at = models.utc_now()

        self.db.commit()
        self.db.refresh(tournament)
        return TournamentRead.model_validate(tournament)

    def reopen_tournament(self, tournament_id: int) -> TournamentRead:
        """Возвращает закрытый турнир в регистрацию (отмена закрытия).

        Инвариант «один активный турнир на чат» проверяем здесь: если в том же чате уже есть
        незакрытый турнир, реоткрытие сделало бы их два, и `get_active_tournament_for_chat`
        начал бы отдавать произвольный. В этом случае — `TournamentAlreadyExists`.
        """
        tournament = get_tournament(self.db, tournament_id)
        ensure_tournament_status(tournament, allowed=[models.TournamentStatus.CLOSED])

        other = self.db.execute(
            select(models.Tournament)
            .where(
                models.Tournament.chat_id == tournament.chat_id,
                models.Tournament.status != models.TournamentStatus.CLOSED,
                models.Tournament.id != tournament.id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if other:
            raise errors.TournamentAlreadyExists(f"Chat {tournament.chat_id} already has active tournament #{other.id}")

        tournament.status = models.TournamentStatus.REGISTRATION
        tournament.ended_at = None
        tournament.registration_open_at = models.utc_now()

        self.db.commit()
        self.db.refresh(tournament)
        return TournamentRead.model_validate(tournament)

    def delete_tournament(self, tournament_id: int) -> None:
        """Полностью удалить турнир и всех его участников из БД (для дебага/сброса)."""
        tournament = get_tournament(self.db, tournament_id)
        self.db.delete(tournament)
        self.db.commit()

    # ===== participants =====

    def register_participant(
        self,
        *,
        tournament_id: int,
        user_id: int,
        archetype_id: Optional[int] = None,
        added_by_admin: bool = False,
        deck_added_by_tg_id: Optional[int] = None,
        deck_deferred: bool = False,
    ) -> ParticipantRead:
        tournament = get_tournament(self.db, tournament_id)
        ensure_tournament_status(tournament, allowed=[models.TournamentStatus.REGISTRATION])

        stmt = select(models.Participant).where(
            models.Participant.tournament_id == tournament_id,
            models.Participant.user_id == user_id,
        )
        existing = self.db.execute(stmt).scalar_one_or_none()
        if existing:
            raise errors.ParticipantAlreadyRegistered(
                f"User {user_id} already registered in tournament {tournament_id}"
            )

        participant = models.Participant(
            tournament_id=tournament_id,
            user_id=user_id,
            archetype_id=archetype_id,
            added_by_admin=added_by_admin,
            deck_added_by_tg_id=deck_added_by_tg_id if archetype_id else None,
            deck_deferred=deck_deferred and archetype_id is None,
            created_at=models.utc_now(),
            updated_at=models.utc_now(),
        )
        self.db.add(participant)
        self.db.commit()
        self.db.refresh(participant)
        return ParticipantRead.model_validate(participant)

    def set_participant_archetype(
        self,
        *,
        participant_id: int,
        archetype_id: Optional[int],
        reset_votes: bool = True,
        deck_added_by_tg_id: Optional[int] = None,
    ) -> ParticipantRead:
        participant = self._get_participant(participant_id)

        participant.archetype_id = archetype_id
        if archetype_id is not None:
            participant.deck_deferred = False
        participant.confirmed = False
        participant.updated_at = models.utc_now()
        if deck_added_by_tg_id is not None:
            participant.deck_added_by_tg_id = deck_added_by_tg_id

        if reset_votes:
            self.db.query(models.Vote).filter(models.Vote.participant_id == participant_id).delete(
                synchronize_session=False
            )
            participant.upvotes_count = 0
            participant.downvotes_count = 0

        self.db.commit()
        self.db.refresh(participant)
        return ParticipantRead.model_validate(participant)

    def mark_participant_deck_deferred(self, participant_id: int) -> ParticipantRead:
        """Mark an existing deckless participant as explicitly choosing «Укажу позже»."""
        participant = self._get_participant(participant_id)
        if participant.archetype_id is None:
            participant.deck_deferred = True
            participant.updated_at = models.utc_now()
            self.db.commit()
            self.db.refresh(participant)
        return ParticipantRead.model_validate(participant)

    def list_participants_for_tournament(
        self,
        tournament_id: int,
    ) -> List[ParticipantWithUserAndArchetype]:
        stmt = (
            select(models.Participant)
            .where(models.Participant.tournament_id == tournament_id)
            .order_by(models.Participant.created_at.asc())
        )
        participants = self.db.execute(stmt).scalars().all()
        return [ParticipantWithUserAndArchetype.model_validate(p) for p in participants]

    def get_deck_recorders(self, tournament_id: int, min_count: int = 2) -> List[DeckRecorder]:
        """Метаписцы: кто записал ≥ ``min_count`` колод в турнире, по убыванию количества.

        Считаем по ``deck_added_by_tg_id`` участников с колодой (сам игрок, админ или оппонент).
        """
        rows = self.db.execute(
            select(
                models.User.username,
                models.User.first_name,
                models.User.last_name,
                func.count(models.Participant.id).label("cnt"),
            )
            .join(models.User, models.User.tg_id == models.Participant.deck_added_by_tg_id)
            .where(
                models.Participant.tournament_id == tournament_id,
                models.Participant.archetype_id.isnot(None),
                models.Participant.deck_added_by_tg_id.isnot(None),
            )
            .group_by(models.User.id, models.User.username, models.User.first_name, models.User.last_name)
            .having(func.count(models.Participant.id) >= min_count)
            .order_by(func.count(models.Participant.id).desc(), models.User.last_name.asc())
        ).all()
        return [
            DeckRecorder(username=r.username, first_name=r.first_name, last_name=r.last_name, count=r.cnt) for r in rows
        ]

    def get_participant_by_id(self, participant_id: int) -> Optional[models.Participant]:
        """Вернуть участника по participant.id или None."""
        stmt = select(models.Participant).where(models.Participant.id == participant_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_participant(self, tournament_id: int, user_id: int) -> Optional[models.Participant]:
        """Вернуть участника турнира по user_id или None."""
        stmt = select(models.Participant).where(
            models.Participant.tournament_id == tournament_id,
            models.Participant.user_id == user_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def unregister_participant(self, tournament_id: int, user_id: int) -> None:
        """Удалить участника из турнира. Raises ParticipantNotFound если не найден."""
        participant = self.get_participant(tournament_id, user_id)
        if participant is None:
            raise errors.ParticipantNotFound()
        self.db.delete(participant)
        self.db.commit()

    def bulk_add_participants(
        self,
        tournament_id: int,
        entries: list[tuple[int, str]],
    ) -> list[tuple[str, str]]:
        """Массово добавить участников без архетипа.

        entries: список (user_id, display_name).
        Возвращает список (display_name, status) где status — "added" | "already_registered".
        Raises TournamentNotFound, TournamentInvalidState.
        Commit делается один раз в конце.
        """
        tournament = get_tournament(self.db, tournament_id)
        ensure_tournament_status(tournament, allowed=[models.TournamentStatus.REGISTRATION])

        results: list[tuple[str, str]] = []
        registered_in_batch: set[int] = set()

        for user_id, display_name in entries:
            if user_id in registered_in_batch or self.get_participant(tournament_id, user_id):
                results.append((display_name, "already_registered"))
                continue
            participant = models.Participant(
                tournament_id=tournament_id,
                user_id=user_id,
                archetype_id=None,
                added_by_admin=True,
                created_at=models.utc_now(),
                updated_at=models.utc_now(),
            )
            self.db.add(participant)
            registered_in_batch.add(user_id)
            results.append((display_name, "added"))

        self.db.commit()
        return results

    # ===== voting =====

    def cast_vote(
        self,
        *,
        tournament_id: int,
        participant_id: int,
        voter_user_id: int,
        vote_type: models.VoteType,
        apply_cooldown: bool = True,
    ) -> VoteRead:
        tournament = get_tournament(self.db, tournament_id)
        ensure_tournament_status(tournament, allowed=[models.TournamentStatus.ONGOING])

        participant = self._get_participant(participant_id)

        if participant.tournament_id != tournament_id:
            raise errors.VotingNotAllowed("Participant does not belong to this tournament")

        if participant.user_id == voter_user_id:
            raise errors.SelfVoteNotAllowed("User cannot vote for their own deck")

        voter = self.db.get(models.User, voter_user_id)
        if not voter:
            raise errors.VotingNotAllowed(f"Voter user {voter_user_id} does not exist")

        existing_vote = self._get_vote(
            tournament_id=tournament_id,
            participant_id=participant_id,
            voter_id=voter_user_id,
        )

        now = models.utc_now()

        if existing_vote:
            if apply_cooldown and now - existing_vote.created_at < CHANGE_VOTE_COOLDOWN:
                raise errors.VotingNotAllowed("Vote change cooldown is active")

            if existing_vote.vote_type == vote_type:
                return VoteRead.model_validate(existing_vote)

            if existing_vote.vote_type == models.VoteType.UP:
                participant.upvotes_count = max(0, participant.upvotes_count - 1)
            else:
                participant.downvotes_count = max(0, participant.downvotes_count - 1)

            existing_vote.vote_type = vote_type
            existing_vote.created_at = now
            if vote_type == models.VoteType.UP:
                participant.upvotes_count += 1
            else:
                participant.downvotes_count += 1

            self._recalculate_confirmation(participant)
            participant.updated_at = now

            self.db.commit()
            self.db.refresh(existing_vote)
            return VoteRead.model_validate(existing_vote)

        vote = models.Vote(
            tournament_id=tournament_id,
            participant_id=participant_id,
            voter_id=voter_user_id,
            vote_type=vote_type,
            created_at=now,
        )

        if vote_type == models.VoteType.UP:
            participant.upvotes_count += 1
        else:
            participant.downvotes_count += 1

        self._recalculate_confirmation(participant)
        participant.updated_at = now

        self.db.add(vote)
        self.db.commit()
        self.db.refresh(vote)
        return VoteRead.model_validate(vote)

    def reset_votes_for_participant(self, participant_id: int) -> None:
        participant = self._get_participant(participant_id)

        self.db.query(models.Vote).filter(models.Vote.participant_id == participant_id).delete(
            synchronize_session=False
        )

        participant.upvotes_count = 0
        participant.downvotes_count = 0
        participant.confirmed = False
        participant.updated_at = models.utc_now()

        self.db.commit()
