import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    Integer,
    String,
    DateTime,
    Enum,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from core.database import Base


class TournamentStatus(str, enum.Enum):
    REGISTRATION = "registration"
    ONGOING = "ongoing"
    VOTING = "voting"
    CLOSED = "closed"


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

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    participants = relationship("Participant", back_populates="user", cascade="all, delete-orphan")
    votes = relationship("Vote", back_populates="voter", cascade="all, delete-orphan")


class Tournament(Base):
    __tablename__ = "tournaments"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    chat_id = Column(BigInteger, nullable=False, index=True)  # id группового чата
    slug = Column(String(64), nullable=True, index=True)   # например "2026-01-31-pauper"

    status = Column(Enum(TournamentStatus), default=TournamentStatus.REGISTRATION, nullable=False)

    registration_open_at = Column(DateTime, nullable=True)
    registration_close_at = Column(DateTime, nullable=True)

    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    participants = relationship("Participant", back_populates="tournament", cascade="all, delete-orphan")
    votes = relationship("Vote", back_populates="tournament", cascade="all, delete-orphan")


class Archetype(Base):
    __tablename__ = "archetypes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)  # "Burn"
    color_emoji = Column(String(8), nullable=True)           # "🔴"
    short_name = Column(String(64), nullable=True)           # "RDW"

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    participants = relationship("Participant", back_populates="archetype")

    aliases = relationship("ArchetypeAlias", back_populates="archetype", cascade="all, delete-orphan")


class ArchetypeAlias(Base):
    """Синонимы архетипов для фуззи-поиска по названию."""

    __tablename__ = "archetype_aliases"

    id = Column(Integer, primary_key=True, index=True)
    archetype_id = Column(Integer, ForeignKey("archetypes.id", ondelete="CASCADE"), nullable=False)
    alias = Column(String(255), nullable=False, index=True)

    archetype = relationship("Archetype", back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("archetype_id", "alias", name="uq_archetype_alias"),
    )


class Participant(Base):
    """Игрок в рамках конкретного турнира."""

    __tablename__ = "participants"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    archetype_id = Column(Integer, ForeignKey("archetypes.id", ondelete="SET NULL"), nullable=True)

    # был добавлен самим игроком или админом
    added_by_admin = Column(Boolean, default=False, nullable=False)

    # подтверждена ли колода (по голосованию или руками админа)
    confirmed = Column(Boolean, default=False, nullable=False)

    upvotes_count = Column(Integer, default=0, nullable=False)
    downvotes_count = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    tournament = relationship("Tournament", back_populates="participants")
    user = relationship("User", back_populates="participants")
    archetype = relationship("Archetype", back_populates="participants")
    votes = relationship("Vote", back_populates="participant", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("tournament_id", "user_id", name="uq_tournament_user"),
        Index("ix_tournament_archetype", "tournament_id", "archetype_id"),
    )


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

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    tournament = relationship("Tournament", back_populates="votes")
    participant = relationship("Participant", back_populates="votes")
    voter = relationship("User", back_populates="votes")

    __table_args__ = (
        # один голос (up/down) voter → participant в рамках турнира
        UniqueConstraint("tournament_id", "participant_id", "voter_id", name="uq_vote_unique"),
        Index("ix_votes_tournament_voter", "tournament_id", "voter_id"),
    )
