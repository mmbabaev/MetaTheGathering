import enum
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from core.database import Base


def utc_now() -> datetime:
    """Current UTC time as naive datetime (matches SQLAlchemy DateTime without timezone=True / SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TournamentStatus(str, enum.Enum):
    REGISTRATION = "registration"
    ONGOING = "ongoing"
    VOTING = "voting"
    CLOSED = "closed"

    @property
    def label_ru(self) -> str:
        return {
            TournamentStatus.REGISTRATION: "Регистрация",
            TournamentStatus.ONGOING: "Идёт",
            TournamentStatus.VOTING: "Голосование",
            TournamentStatus.CLOSED: "Завершён",
        }.get(self, self.value)


class User(Base):
    """Телеграм-пользователь в контексте бота (игрок/админ)."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)

    is_admin = Column(Boolean, default=False, nullable=False)
    is_superadmin = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=utc_now, nullable=False)

    participants = relationship("Participant", back_populates="user", cascade="all, delete-orphan")
    votes = relationship("Vote", back_populates="voter", cascade="all, delete-orphan")
    deck_history = relationship("UserDeckHistory", back_populates="user", cascade="all, delete-orphan")


class Tournament(Base):
    __tablename__ = "tournaments"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    chat_id = Column(BigInteger, nullable=False, index=True)  # id группового чата
    slug = Column(String(64), nullable=True, index=True)  # например "2026-01-31-pauper"

    status = Column(Enum(TournamentStatus), default=TournamentStatus.REGISTRATION, nullable=False)
    club = Column(String(64), nullable=True, index=True)  # "Goldfish" / "Edinorog" / None

    registration_open_at = Column(DateTime, nullable=True)
    registration_close_at = Column(DateTime, nullable=True)

    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)

    decks_hidden = Column(Boolean, nullable=False, default=True, server_default="true")
    aetherhub_url = Column(String(512), nullable=True)
    aetherhub_import_time = Column(String(5), nullable=True)  # "HH:MM" — scheduled auto-import time

    created_at = Column(DateTime, default=utc_now, nullable=False)

    participants = relationship("Participant", back_populates="tournament", cascade="all, delete-orphan")
    votes = relationship("Vote", back_populates="tournament", cascade="all, delete-orphan")
    poll = relationship("TournamentPoll", back_populates="tournament", uselist=False, cascade="all, delete-orphan")


class Archetype(Base):
    __tablename__ = "archetypes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)  # "Burn"
    color_emoji = Column(String(8), nullable=True)  # "🔴"
    short_name = Column(String(64), nullable=True)  # "RDW"
    meta_rank = Column(Integer, nullable=True, index=True)  # позиция в топ-мета (1=первый); NULL — нет места в списке
    is_custom = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )  # True = введён игроком вручную; не показывается в глобальном топе

    created_at = Column(DateTime, default=utc_now, nullable=False)

    participants = relationship("Participant", back_populates="archetype")
    user_history = relationship("UserDeckHistory", back_populates="archetype", cascade="all, delete-orphan")

    aliases = relationship("ArchetypeAlias", back_populates="archetype", cascade="all, delete-orphan")


class ArchetypeAlias(Base):
    """Синонимы архетипов для фуззи-поиска по названию."""

    __tablename__ = "archetype_aliases"

    id = Column(Integer, primary_key=True, index=True)
    archetype_id = Column(Integer, ForeignKey("archetypes.id", ondelete="CASCADE"), nullable=False)
    alias = Column(String(255), nullable=False, index=True)

    archetype = relationship("Archetype", back_populates="aliases")

    __table_args__ = (UniqueConstraint("archetype_id", "alias", name="uq_archetype_alias"),)


class Participant(Base):
    """Игрок в рамках конкретного турнира."""

    __tablename__ = "participants"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    archetype_id = Column(Integer, ForeignKey("archetypes.id", ondelete="SET NULL"), nullable=True)

    # был добавлен самим игроком или админом
    added_by_admin = Column(Boolean, default=False, nullable=False)

    # tg_id того, кто записал колоду (сам игрок, админ или оппонент)
    deck_added_by_tg_id = Column(BigInteger, nullable=True)

    # подтверждена ли колода (по голосованию или руками админа)
    confirmed = Column(Boolean, default=False, nullable=False)

    upvotes_count = Column(Integer, default=0, nullable=False)
    downvotes_count = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)
    last_dm_at = Column(DateTime, nullable=True)

    tournament = relationship("Tournament", back_populates="participants")
    user = relationship("User", back_populates="participants")
    archetype = relationship("Archetype", back_populates="participants")
    votes = relationship("Vote", back_populates="participant", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("tournament_id", "user_id", name="uq_tournament_user"),
        Index("ix_tournament_archetype", "tournament_id", "archetype_id"),
    )


class UserDeckHistory(Base):
    """История колод игрока из внешних источников (DataLens import и т.п.).

    Используется для показа подсказок при регистрации на турнир.
    Не привязана к конкретному турниру — хранит «когда-либо играл».
    """

    __tablename__ = "user_deck_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    archetype_id = Column(Integer, ForeignKey("archetypes.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(64), nullable=True)  # напр. "datalens_import"

    created_at = Column(DateTime, default=utc_now, nullable=False)

    user = relationship("User", back_populates="deck_history")
    archetype = relationship("Archetype", back_populates="user_history")

    __table_args__ = (UniqueConstraint("user_id", "archetype_id", name="uq_user_deck_history"),)


class VoteType(str, enum.Enum):
    UP = "up"
    DOWN = "down"


class Vote(Base):
    """Голос за конкретного участника (его архетип) в рамках турнира."""

    __tablename__ = "votes"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False)
    participant_id = Column(Integer, ForeignKey("participants.id", ondelete="CASCADE"), nullable=False)
    voter_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    vote_type = Column(Enum(VoteType), nullable=False)

    created_at = Column(DateTime, default=utc_now, nullable=False)

    tournament = relationship("Tournament", back_populates="votes")
    participant = relationship("Participant", back_populates="votes")
    voter = relationship("User", back_populates="votes")

    __table_args__ = (
        # один голос (up/down) voter → participant в рамках турнира
        UniqueConstraint("tournament_id", "participant_id", "voter_id", name="uq_vote_unique"),
        Index("ix_votes_tournament_voter", "tournament_id", "voter_id"),
    )


class TournamentPoll(Base):
    """Telegram-опрос «Пойду / Не пойду» привязанный к турниру."""

    __tablename__ = "tournament_polls"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, unique=True)
    chat_id = Column(BigInteger, nullable=False)
    tg_poll_id = Column(String, nullable=False, unique=True)
    message_id = Column(BigInteger, nullable=False)
    chat_username = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    tournament = relationship("Tournament", back_populates="poll")
    votes = relationship("PollVote", back_populates="poll", cascade="all, delete-orphan")


class PollVote(Base):
    """Голос одного пользователя в опросе турнира."""

    __tablename__ = "poll_votes"

    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, ForeignKey("tournament_polls.id", ondelete="CASCADE"), nullable=False)
    tg_user_id = Column(BigInteger, nullable=False)
    choice = Column(Integer, nullable=False)  # 0 = пойду, 1 = не пойду

    poll = relationship("TournamentPoll", back_populates="votes")

    __table_args__ = (UniqueConstraint("poll_id", "tg_user_id", name="uq_poll_vote_unique"),)


class RoundPairing(Base):
    """Паринг одного игрока в конкретном раунде турнира (импорт из AetherHub)."""

    __tablename__ = "round_pairings"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False)
    round_number = Column(Integer, nullable=False)
    player_name = Column(String(255), nullable=False)
    opponent_name = Column(String(255), nullable=True)  # NULL = bye

    __table_args__ = (UniqueConstraint("tournament_id", "round_number", "player_name", name="uq_round_pairing"),)
