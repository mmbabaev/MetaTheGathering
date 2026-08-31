from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from core.models import TournamentStatus, VoteType

# ==== Archetype ====


class ArchetypeBase(BaseModel):
    name: str
    color_emoji: Optional[str] = None
    short_name: Optional[str] = None


class ArchetypeCreate(ArchetypeBase):
    aliases: Optional[List[str]] = None


class ArchetypeRead(ArchetypeBase):
    id: int
    macro_name: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ArchetypeWithAliases(ArchetypeRead):
    aliases: List[str] = []


# ==== User ====


class UserBase(BaseModel):
    tg_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class UserCreate(UserBase):
    pass


class UserRead(UserBase):
    id: int
    is_admin: bool
    is_superadmin: bool
    is_scorekeeper: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==== Tournament ====


class TournamentBase(BaseModel):
    title: str
    chat_id: int
    slug: Optional[str] = None
    club: Optional[str] = None


class TournamentCreate(TournamentBase):
    registration_close_at: Optional[datetime] = None


class TournamentRead(TournamentBase):
    id: int
    status: TournamentStatus
    decks_hidden: bool = True
    aetherhub_url: Optional[str] = None
    aetherhub_import_time: Optional[str] = None
    registration_open_at: Optional[datetime] = None
    registration_close_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    closed_by_tg_id: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==== Participant ====


class ParticipantBase(BaseModel):
    tournament_id: int
    user_id: int
    archetype_id: Optional[int] = None


class ParticipantCreate(ParticipantBase):
    added_by_admin: bool = False


class ParticipantRead(ParticipantBase):
    id: int
    confirmed: bool
    added_by_admin: bool
    deck_deferred: bool = False
    deck_reminder_prestart_sent_at: Optional[datetime] = None
    deck_reminder_round2_sent_at: Optional[datetime] = None
    aetherhub_seen_at: Optional[datetime] = None
    upvotes_count: int
    downvotes_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ParticipantWithUserAndArchetype(ParticipantRead):
    user: UserRead
    archetype: Optional[ArchetypeRead] = None


# ==== Vote ====


class VoteBase(BaseModel):
    tournament_id: int
    participant_id: int
    voter_id: int
    vote_type: VoteType


class VoteCreate(VoteBase):
    pass


class VoteRead(VoteBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
