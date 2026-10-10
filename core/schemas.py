from datetime import datetime

from pydantic import BaseModel, ConfigDict

from core.models import TournamentEngineMode, TournamentStatus, VoteType

# ==== Archetype ====


class ArchetypeBase(BaseModel):
    name: str
    color_emoji: str | None = None
    short_name: str | None = None


class ArchetypeCreate(ArchetypeBase):
    aliases: list[str] | None = None


class ArchetypeRead(ArchetypeBase):
    id: int
    macro_name: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ArchetypeWithAliases(ArchetypeRead):
    aliases: list[str] = []


# ==== User ====


class UserBase(BaseModel):
    tg_id: int
    username: str | None = None
    endstep_username: str | None = None
    city: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class UserCreate(UserBase):
    pass


class UserRead(UserBase):
    id: int
    is_admin: bool
    is_superadmin: bool
    is_scorekeeper: bool
    is_tournament_organizer: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==== Tournament ====


class TournamentBase(BaseModel):
    title: str
    chat_id: int
    slug: str | None = None
    club: str | None = None
    is_online: bool = False
    is_draft: bool = False
    engine_mode: str = TournamentEngineMode.AETHERHUB


class TournamentCreate(TournamentBase):
    registration_close_at: datetime | None = None
    created_by_tg_id: int | None = None
    decklist_reminders_enabled: bool = True


class TournamentRead(TournamentBase):
    id: int
    status: TournamentStatus
    decks_hidden: bool = True
    show_round_pairings: bool = False
    swiss_rounds: int | None = None
    playoff_size: int | None = None
    swiss_large_format: bool = False
    draft_seating_generated_at: datetime | None = None
    aetherhub_url: str | None = None
    aetherhub_import_time: str | None = None
    registration_open_at: datetime | None = None
    registration_close_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    closed_by_tg_id: int | None = None
    created_by_tg_id: int | None = None
    decklist_reminders_enabled: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==== Participant ====


class ParticipantBase(BaseModel):
    tournament_id: int
    user_id: int
    archetype_id: int | None = None


class ParticipantCreate(ParticipantBase):
    added_by_admin: bool = False


class ParticipantRead(ParticipantBase):
    id: int
    confirmed: bool
    added_by_admin: bool
    deck_deferred: bool = False
    deck_reminder_prestart_sent_at: datetime | None = None
    deck_reminder_round2_sent_at: datetime | None = None
    swiss_requirements_reminder_sent_at: datetime | None = None
    aetherhub_seen_at: datetime | None = None
    ranked_activated_at: datetime | None = None
    ranked_activation_source: str | None = None
    swiss_initial_rank: int | None = None
    playoff_seed: int | None = None
    upvotes_count: int
    downvotes_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ParticipantWithUserAndArchetype(ParticipantRead):
    user: UserRead
    archetype: ArchetypeRead | None = None


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
