from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from core import models
from core.schemas import (
    TournamentCreate,
    TournamentRead,
    ParticipantRead,
    ParticipantWithUserAndArchetype,
    VoteRead,
)
from services import errors
from services.utils import get_tournament, ensure_tournament_status


# доменные настройки
CONFIRM_THRESHOLD = 3   # up - down >= 3 → confirmed = True
REJECT_THRESHOLD = 3    # down - up >= 3 → confirmed = False
CHANGE_VOTE_COOLDOWN = timedelta(seconds=30)


@dataclass
class ArchetypeItem:
    id: int
    name: str


@dataclass
class MetaRow:
    archetype_id: int
    archetype_name: str
    count: int
    upvotes_sum: int
    downvotes_sum: int


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
            raise errors.TournamentAlreadyExists(
                f"Chat {data.chat_id} already has active tournament #{active.id}"
            )

        tournament = models.Tournament(
            title=data.title,
            chat_id=data.chat_id,
            slug=data.slug,
            status=models.TournamentStatus.REGISTRATION,
            created_at=datetime.utcnow(),
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

    def list_all_active_tournaments(self) -> List[TournamentRead]:
        """Все турниры со статусом не CLOSED, по убыванию created_at."""
        stmt = (
            select(models.Tournament)
            .where(models.Tournament.status != models.TournamentStatus.CLOSED)
            .order_by(models.Tournament.created_at.desc())
        )
        rows = self.db.execute(stmt).scalars().all()
        return [TournamentRead.model_validate(t) for t in rows]

    def list_archetypes(self) -> List[ArchetypeItem]:
        """Список всех архетипов (id, name)."""
        stmt = select(models.Archetype).order_by(models.Archetype.name.asc())
        rows = self.db.execute(stmt).scalars().all()
        return [ArchetypeItem(id=a.id, name=a.name) for a in rows]

    def list_archetypes_for_user(self, tg_id: int, total: int = 10) -> List[ArchetypeItem]:
        """Топ-N архетипов: последние выборы пользователя первыми, остальные по алфавиту."""
        all_archetypes = self.list_archetypes()

        # Ищем последние выборы пользователя (самые новые сначала, без дублей)
        user_stmt = select(models.User).where(models.User.tg_id == tg_id)
        user = self.db.execute(user_stmt).scalar_one_or_none()

        recent_ids: list[int] = []
        if user:
            hist_stmt = (
                select(models.Participant.archetype_id)
                .where(
                    models.Participant.user_id == user.id,
                    models.Participant.archetype_id.isnot(None),
                )
                .order_by(models.Participant.created_at.desc())
            )
            seen: set[int] = set()
            for (aid,) in self.db.execute(hist_stmt).all():
                if aid not in seen:
                    seen.add(aid)
                    recent_ids.append(aid)

        recent_set = set(recent_ids)
        recent_map = {aid: i for i, aid in enumerate(recent_ids)}

        recent = sorted(
            [a for a in all_archetypes if a.id in recent_set],
            key=lambda a: recent_map[a.id],
        )
        rest = [a for a in all_archetypes if a.id not in recent_set]

        return (recent + rest)[:total]

    def get_or_create_user(
        self,
        *,
        tg_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> models.User:
        """Найти пользователя по tg_id или создать нового."""
        stmt = select(models.User).where(models.User.tg_id == tg_id)
        user = self.db.execute(stmt).scalar_one_or_none()
        if user:
            return user
        user = models.User(
            tg_id=tg_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_or_create_archetype_by_name(self, name: str) -> models.Archetype:
        """Найти архетип по имени или создать новый."""
        stmt = select(models.Archetype).where(models.Archetype.name == name)
        archetype = self.db.execute(stmt).scalar_one_or_none()
        if archetype:
            return archetype
        archetype = models.Archetype(name=name.strip())
        self.db.add(archetype)
        self.db.commit()
        self.db.refresh(archetype)
        return archetype

    def open_registration(self, tournament_id: int) -> TournamentRead:
        tournament = get_tournament(self.db, tournament_id)
        tournament.status = models.TournamentStatus.REGISTRATION
        tournament.registration_open_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(tournament)
        return TournamentRead.model_validate(tournament)

    def start_tournament(self, tournament_id: int) -> TournamentRead:
        tournament = get_tournament(self.db, tournament_id)
        ensure_tournament_status(
            tournament,
            allowed=[models.TournamentStatus.REGISTRATION, models.TournamentStatus.VOTING],
        )

        tournament.status = models.TournamentStatus.ONGOING
        if not tournament.started_at:
            tournament.started_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(tournament)
        return TournamentRead.model_validate(tournament)

    def open_voting(self, tournament_id: int) -> TournamentRead:
        tournament = get_tournament(self.db, tournament_id)
        ensure_tournament_status(
            tournament,
            allowed=[models.TournamentStatus.REGISTRATION, models.TournamentStatus.ONGOING],
        )

        tournament.status = models.TournamentStatus.VOTING
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
                models.TournamentStatus.VOTING,
            ],
        )

        tournament.status = models.TournamentStatus.CLOSED
        tournament.ended_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(tournament)
        return TournamentRead.model_validate(tournament)

    # ===== participants =====

    def register_participant(
        self,
        *,
        tournament_id: int,
        user_id: int,
        archetype_id: Optional[int] = None,
        added_by_admin: bool = False,
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
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
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
    ) -> ParticipantRead:
        participant = self._get_participant(participant_id)

        participant.archetype_id = archetype_id
        participant.confirmed = False
        participant.updated_at = datetime.utcnow()

        if reset_votes:
            self.db.query(models.Vote).filter(
                models.Vote.participant_id == participant_id
            ).delete(synchronize_session=False)
            participant.upvotes_count = 0
            participant.downvotes_count = 0

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
        ensure_tournament_status(tournament, allowed=[models.TournamentStatus.VOTING])

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

        now = datetime.utcnow()

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

        self.db.query(models.Vote).filter(
            models.Vote.participant_id == participant_id
        ).delete(synchronize_session=False)

        participant.upvotes_count = 0
        participant.downvotes_count = 0
        participant.confirmed = False
        participant.updated_at = datetime.utcnow()

        self.db.commit()

    # ===== meta =====

    def get_tournament_meta(self, tournament_id: int) -> List[MetaRow]:
        stmt = (
            select(
                models.Archetype.id.label("archetype_id"),
                models.Archetype.name.label("archetype_name"),
                func.count(models.Participant.id).label("count"),
                func.sum(models.Participant.upvotes_count).label("upvotes_sum"),
                func.sum(models.Participant.downvotes_count).label("downvotes_sum"),
            )
            .join(models.Participant, models.Participant.archetype_id == models.Archetype.id)
            .where(models.Participant.tournament_id == tournament_id)
            .group_by(models.Archetype.id, models.Archetype.name)
            .order_by(func.count(models.Participant.id).desc())
        )

        rows = self.db.execute(stmt).all()
        return [
            MetaRow(
                archetype_id=row.archetype_id,
                archetype_name=row.archetype_name,
                count=row.count or 0,
                upvotes_sum=row.upvotes_sum or 0,
                downvotes_sum=row.downvotes_sum or 0,
            )
            for row in rows
        ]
