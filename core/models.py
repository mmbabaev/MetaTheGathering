import enum
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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
    CLOSED = "closed"

    @property
    def label_ru(self) -> str:
        return {
            TournamentStatus.REGISTRATION: "Регистрация",
            TournamentStatus.ONGOING: "Идёт",
            TournamentStatus.CLOSED: "Завершён",
        }.get(self, self.value)


class User(Base):
    """Пользователь — Telegram-аккаунт или веб-пользователь (отрицательный tg_id)."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    display_name = Column(String(255), nullable=True)
    email = Column(String(255), unique=True, nullable=True, index=True)

    is_admin = Column(Boolean, default=False, nullable=False)
    is_superadmin = Column(Boolean, default=False, nullable=False)
    is_scorekeeper = Column(Boolean, default=False, nullable=False)
    # организатор голосований (дейликов): создаёт опросы через бота и рассылает уведомления (issue #157)
    is_poll_organizer = Column(Boolean, default=False, nullable=False, server_default="false")
    hide_deck_emoji = Column(Boolean, default=False, nullable=False)
    notify_opponent_rounds = Column(Boolean, default=False, nullable=False)
    notify_achievements = Column(Boolean, default=False, nullable=False, server_default="false")
    notify_poll = Column(
        Boolean, default=False, nullable=False, server_default="false"
    )  # опт-ин на уведомления о голосованиях
    notify_cellar_reservations = Column(Boolean, default=True, nullable=False, server_default="true")
    status_by_pairings = Column(Boolean, default=False, nullable=False)  # статус турнира попарно по парингам

    created_at = Column(DateTime, default=utc_now, nullable=False)

    participants = relationship("Participant", back_populates="user", cascade="all, delete-orphan")
    votes = relationship("Vote", back_populates="voter", cascade="all, delete-orphan")
    deck_history = relationship("UserDeckHistory", back_populates="user", cascade="all, delete-orphan")
    web_auth_tokens = relationship("WebAuthToken", back_populates="user", cascade="all, delete-orphan")
    cellar_reservations = relationship("CellarDeckReservation", back_populates="user", cascade="all, delete-orphan")


class WebLinkRequest(Base):
    """Запрос на привязку веб-аккаунта к Telegram-аккаунту через код."""

    __tablename__ = "web_link_requests"

    id = Column(Integer, primary_key=True, index=True)
    web_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tg_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(6), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class WebAuthToken(Base):
    """Magic-link токен для веб-авторизации."""

    __tablename__ = "web_auth_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)  # SHA-256 hex
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)

    user = relationship("User", back_populates="web_auth_tokens")


class Tournament(Base):
    __tablename__ = "tournaments"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    chat_id = Column(BigInteger, nullable=False, index=True)  # id группового чата
    slug = Column(String(64), nullable=True, index=True)  # например "2026-01-31-pauper"

    status = Column(Enum(TournamentStatus), default=TournamentStatus.REGISTRATION, nullable=False)
    club = Column(String(64), nullable=True, index=True)  # "Goldfish" / "Edinorog" / None
    is_online = Column(Boolean, nullable=False, default=False, server_default="false")
    # Public status screen can show the latest round's pairings and live scores
    # instead of the flat participant list. This is configured per tournament.
    show_round_pairings = Column(Boolean, nullable=False, default=False, server_default="false")

    registration_open_at = Column(DateTime, nullable=True)
    registration_close_at = Column(DateTime, nullable=True)

    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    # Telegram id of the admin who closed the tournament manually; NULL for automatic closure.
    closed_by_tg_id = Column(BigInteger, nullable=True)

    decks_hidden = Column(Boolean, nullable=False, default=True, server_default="true")
    aetherhub_url = Column(String(512), nullable=True)
    aetherhub_import_time = Column(String(5), nullable=True)  # "HH:MM" — scheduled auto-import time
    # owner-only DM after the second scheduled lookup could not find this event on AetherHub
    aetherhub_not_found_notified_at = Column(DateTime, nullable=True)

    # момент отправки анонса «сбор метагейма завершён»; NULL = ещё не анонсировали (идемпотентность)
    completed_announced_at = Column(DateTime, nullable=True)

    # owner-only напоминания о всё ещё незакрытом турнире; ставятся только после успешной доставки
    unclosed_reminder_3d_sent_at = Column(DateTime, nullable=True)
    unclosed_reminder_7d_sent_at = Column(DateTime, nullable=True)

    # просьба в чат заполнить недостающие колоды на следующий день после турнира
    missing_decks_reminder_1d_sent_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)

    participants = relationship("Participant", back_populates="tournament", cascade="all, delete-orphan")
    votes = relationship("Vote", back_populates="tournament", cascade="all, delete-orphan")
    poll = relationship("TournamentPoll", back_populates="tournament", uselist=False, cascade="all, delete-orphan")
    registration_messages = relationship(
        "TournamentRegistrationMessage", back_populates="tournament", cascade="all, delete-orphan"
    )
    missing_decks_reminder_message = relationship(
        "TournamentMissingDecksReminder",
        back_populates="tournament",
        uselist=False,
        cascade="all, delete-orphan",
    )
    cellar_reservations = relationship("CellarDeckReservation", back_populates="tournament")
    round_matches = relationship("RoundMatch", back_populates="tournament", cascade="all, delete-orphan")


class TournamentRegistrationMessage(Base):
    """Latest registration announcement for a tournament and target chat."""

    __tablename__ = "tournament_registration_messages"

    id = Column(Integer, primary_key=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    base_text = Column(Text, nullable=False)
    button_url = Column(String(512), nullable=True)
    rendered_participant_count = Column(Integer, nullable=False)
    edit_disabled_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)

    tournament = relationship("Tournament", back_populates="registration_messages")

    __table_args__ = (UniqueConstraint("tournament_id", "chat_id", name="uq_tournament_registration_message_target"),)


class TournamentMissingDecksReminder(Base):
    """Telegram message state for the editable meta-police reminder."""

    __tablename__ = "tournament_missing_decks_reminders"

    id = Column(Integer, primary_key=True)
    tournament_id = Column(
        Integer,
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    participant_ids_json = Column(Text, nullable=False)
    button_url = Column(String(512), nullable=True)
    edit_disabled_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)

    tournament = relationship("Tournament", back_populates="missing_decks_reminder_message")


class Archetype(Base):
    __tablename__ = "archetypes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)  # "Burn"
    color_emoji = Column(String(8), nullable=True)  # "🔴"
    # Цветовая идентичность колоды как подмножество WUBRG: "U", "WU", "UBR"…
    # "" = бесцветная, NULL = ещё не определяли. Определяется один раз и кэшируется (см. services/deck_colors.py).
    color_identity = Column(String(8), nullable=True)
    short_name = Column(String(64), nullable=True)  # "RDW"
    # Общий («канонический») тип колоды: разные записи одной деки сводятся сюда
    # («Blue Delver»/«Blue Terror» → «Blue Terror»). Кэш из services/deck_mapping; NULL — не определяли.
    general_name = Column(String(255), nullable=True, index=True)
    # Крупная стратегическая группа поверх general_name (экспериментальный owner-only срез).
    # Например, BG Gardens/BG Pestilence → BG Control; NULL — группа пока не определена.
    macro_name = Column(String(255), nullable=True, index=True)
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


class CellarDeck(Base):
    """One physical deck copy from the Edinorog lending cellar."""

    __tablename__ = "cellar_decks"

    id = Column(Integer, primary_key=True)
    source_key = Column(String(128), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    archetype_name = Column(String(255), nullable=False)
    decklist_url = Column(String(512), nullable=True)
    notes = Column(String(512), nullable=True)
    decklist_updated_on = Column(Date, nullable=True)
    source_position = Column(Integer, nullable=True)
    available = Column(Boolean, nullable=False, default=True, server_default="true")
    active = Column(Boolean, nullable=False, default=True, server_default="true", index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    reservations = relationship("CellarDeckReservation", back_populates="deck", cascade="all, delete-orphan")

    @property
    def display_name(self) -> str:
        return f"{self.name} · №{self.source_position}" if self.source_position is not None else self.name


class CellarDeckReservation(Base):
    """Exclusive reservation of one physical cellar deck for one event date."""

    __tablename__ = "cellar_deck_reservations"

    id = Column(Integer, primary_key=True)
    deck_id = Column(Integer, ForeignKey("cellar_decks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="SET NULL"), nullable=True, index=True)
    participant_id = Column(Integer, ForeignKey("participants.id", ondelete="SET NULL"), nullable=True)
    applied_archetype_id = Column(Integer, ForeignKey("archetypes.id", ondelete="SET NULL"), nullable=True)
    previous_archetype_id = Column(Integer, ForeignKey("archetypes.id", ondelete="SET NULL"), nullable=True)
    previous_deck_added_by_tg_id = Column(BigInteger, nullable=True)
    previous_deck_deferred = Column(Boolean, nullable=True)
    participant_created = Column(Boolean, nullable=False, default=False, server_default="false")
    event_date = Column(Date, nullable=False, index=True)
    group_announced_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    deck = relationship("CellarDeck", back_populates="reservations")
    user = relationship("User", back_populates="cellar_reservations")
    tournament = relationship("Tournament", back_populates="cellar_reservations")

    __table_args__ = (
        Index(
            "uq_active_cellar_deck_event",
            "deck_id",
            "event_date",
            unique=True,
            postgresql_where=cancelled_at.is_(None),
            sqlite_where=cancelled_at.is_(None),
        ),
        Index(
            "uq_active_cellar_user_event",
            "user_id",
            "event_date",
            unique=True,
            postgresql_where=cancelled_at.is_(None),
            sqlite_where=cancelled_at.is_(None),
        ),
    )


class CellarCoordinatorReminder(Base):
    """Idempotency row for one coordinator summary delivery."""

    __tablename__ = "cellar_coordinator_reminders"

    id = Column(Integer, primary_key=True)
    event_date = Column(Date, nullable=False, index=True)
    recipient_tg_id = Column(BigInteger, nullable=False)
    delivered_at = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (UniqueConstraint("event_date", "recipient_tg_id", name="uq_cellar_coordinator_event_recipient"),)


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

    # Игрок сам зарегистрировался через «Укажу позже» и ожидает напоминаний о колоде.
    deck_deferred = Column(Boolean, default=False, nullable=False, server_default="false")
    deck_reminder_prestart_sent_at = Column(DateTime, nullable=True)
    deck_reminder_round2_sent_at = Column(DateTime, nullable=True)

    # подтверждена ли колода (по голосованию или руками админа)
    confirmed = Column(Boolean, default=False, nullable=False)

    final_place = Column(Integer, nullable=True)  # место в финальных стендингах; NULL = не импортировано
    # Последний импорт AetherHub, в котором участник действительно присутствовал.
    aetherhub_seen_at = Column(DateTime, nullable=True)

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


class PollNotification(Base):
    """Кому бот разослал уведомление о голосовании (для ping-списка «кому ещё написать»)."""

    __tablename__ = "poll_notifications"

    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, ForeignKey("tournament_polls.id", ondelete="CASCADE"), nullable=False, index=True)
    tg_user_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (UniqueConstraint("poll_id", "tg_user_id", name="uq_poll_notification_unique"),)


class PollRegular(Base):
    """Регуляр клуба (chat_id) — кого организатор голосований вручную зовёт на дейлики.

    Ping-список «кому ещё написать» = регуляры МИНУС уже уведомлённые ботом и проголосовавшие.
    """

    __tablename__ = "poll_regulars"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(BigInteger, nullable=False, index=True)  # клуб
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (UniqueConstraint("chat_id", "user_id", name="uq_poll_regular_unique"),)


class ClubScheduleRow(Base):
    """Расписание клуба на один день недели — источник правды для планировщика (issue #124/#125).

    Раньше расписание было захардкожено в `get_clubs()`, и любая правка требовала деплоя.
    Теперь строки живут здесь и редактируются админом из `/schedule`; код держит только
    дефолты для первичного сида (`ScheduleService.ensure_defaults`) и идентичность клуба
    (chat_id, ссылка на AetherHub, эмодзи) — это инфраструктура, а не расписание.
    """

    __tablename__ = "club_schedules"

    id = Column(Integer, primary_key=True, index=True)
    club_name = Column(String(64), nullable=False, index=True)  # "Goldfish" / "Edinorog"
    weekday = Column(String(16), nullable=False)  # "monday".."sunday"
    enabled = Column(Boolean, default=True, nullable=False, server_default="true")

    create_time = Column(String(5), nullable=False)  # "12:00" — когда создаём турнир (анонс 1)
    create_days_before = Column(Integer, nullable=False, default=0, server_default="0")
    game_time = Column(String(5), nullable=False)  # "19:30" — время игры, идёт в текст анонса
    reminder_time = Column(String(5), nullable=True)  # "19:25" — напоминание (анонс 2); NULL = выключено
    import_times = Column(String(512), nullable=False, default="")  # CSV "20:00,20:30"; "" = импортов нет

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (UniqueConstraint("club_name", "weekday", name="uq_club_schedule_day"),)


class FeatureFlag(Base):
    """Глобальный feature flag — вкл/выкл функциональности для всех чатов."""

    __tablename__ = "feature_flags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=False)
    value_type = Column(String(16), nullable=False, default="bool")
    default_value = Column(String(64), nullable=False)
    current_value = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"


class Payment(Base):
    """Платёж участника за турнир через ЮKassa."""

    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, nullable=False, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False)
    amount = Column(String(16), nullable=False)  # "525.00"
    yookassa_payment_id = Column(String(64), nullable=True, unique=True)
    status = Column(
        Enum(PaymentStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=PaymentStatus.PENDING,
        nullable=False,
    )
    confirmation_url = Column(String(512), nullable=True)
    tg_chat_id = Column(BigInteger, nullable=True)
    tg_message_id = Column(BigInteger, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class UserAchievement(Base):
    """Выданная игроку ачивка. Одна строка = (игрок, код, уровень) навсегда.

    Уникальный ключ (user_id, code, level) — он же механизм идемпотентности: движок
    переоценивает турниры сколько угодно раз, дубля не будет. ``notified_at`` — когда
    про ачивку сообщили (в теневом режиме — владельцу, см. docs/achievements.md §6).
    """

    __tablename__ = "user_achievements"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(32), nullable=False)  # "undefeated"
    level = Column(Integer, nullable=False, default=1)  # 1/2/3 у многоуровневых
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="SET NULL"), nullable=True)
    progress_value = Column(Integer, nullable=True)  # значение счётчика на момент выдачи
    evidence = Column(String(512), nullable=True)  # причина: «4-0 на Elves», «серия 03.07…24.07»
    awarded_at = Column(DateTime, default=utc_now, nullable=False)
    notified_at = Column(DateTime, nullable=True)  # NULL = ещё не сообщили

    __table_args__ = (UniqueConstraint("user_id", "code", "level", name="uq_user_achievement"),)


class UserAchievementProgress(Base):
    """Текущее значение счётчика ачивки у игрока. Одна строка = (игрок, код).

    Величина производная: правило всегда пересчитывает её из первичных данных, а таблица
    хранит последний снапшот. Нужна только чтобы показать дельту («стало 2/3, +1 за этот
    турнир») — её можно снести и пересобрать бэкафиллом, рассинхрон невозможен.
    """

    __tablename__ = "user_achievement_progress"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(32), nullable=False)
    value = Column(Integer, nullable=False, default=0)  # 2 деки, 7 колод, серия 3
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="SET NULL"), nullable=True)
    evidence = Column(String(512), nullable=True)  # из чего сложилось (для сообщения)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "code", name="uq_user_achievement_progress"),)


class AchievementReportDelivery(Base):
    """Одна versioned delivery владельцу или конкретному игроку.

    Owner и player delivery представлены независимыми строками и статусами. Player
    delivery всегда адресована одному ``user_id``; массового recipient здесь нет.
    """

    __tablename__ = "achievement_report_deliveries"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(String(32), nullable=False, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_type = Column(String(16), nullable=False, default="owner")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    chat_id = Column(BigInteger, nullable=True)
    message_index = Column(Integer, nullable=False)
    payload_type = Column(String(32), nullable=False, default="achievement_report")
    payload_version = Column(Integer, nullable=False, default=1)
    payload = Column(Text, nullable=False)
    idempotency_key = Column(String(160), nullable=True, unique=True)
    status = Column(String(16), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    sent_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("report_id", "message_index", name="uq_achievement_report_delivery_message"),
        CheckConstraint(
            "recipient_type != 'player' OR (user_id IS NOT NULL AND chat_id IS NOT NULL)",
            name="ck_achievement_player_delivery_targeted",
        ),
        CheckConstraint("payload_version > 0", name="ck_achievement_delivery_payload_version"),
    )


class AchievementProcessingLease(Base):
    """Межпроцессная аренда права считать и доставлять ачивки одного турнира."""

    __tablename__ = "achievement_processing_leases"

    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), primary_key=True)
    token = Column(String(32), nullable=False, unique=True)
    locked_until = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class AchievementProcessingRun(Base):
    """Аудит одного завершённого расчёта правил ачивок."""

    __tablename__ = "achievement_processing_runs"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(16), nullable=False, index=True)  # completed / partial / failed
    engine_version = Column(Integer, nullable=False, default=1)
    rules_total = Column(Integer, nullable=False)
    rules_failed = Column(Integer, nullable=False, default=0)
    granted_count = Column(Integer, nullable=False, default=0)
    progress_changes_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    rule_errors_json = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=False)


class AchievementProgressEvent(Base):
    """Неизменяемое объяснение одного перехода achievement progress."""

    __tablename__ = "achievement_progress_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(32), nullable=False, index=True)
    event_type = Column(String(24), nullable=False, default="calculated")
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="SET NULL"), nullable=True, index=True)
    processing_run_id = Column(
        Integer, ForeignKey("achievement_processing_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    before_value = Column(Integer, nullable=False)
    after_value = Column(Integer, nullable=False)
    evidence = Column(String(512), nullable=True)
    requirements_json = Column(Text, nullable=False)
    source_tournament_ids_json = Column(Text, nullable=False)
    match_ids_json = Column(Text, nullable=False)
    stats_snapshot_json = Column(Text, nullable=False)
    ruleset_version = Column(Integer, nullable=False)
    stats_version = Column(String(32), nullable=False)
    idempotency_key = Column(String(160), nullable=False, unique=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class RoundPairing(Base):
    """Паринг одного игрока в конкретном раунде турнира (импорт из AetherHub)."""

    __tablename__ = "round_pairings"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False)
    round_number = Column(Integer, nullable=False)
    player_name = Column(String(255), nullable=False)
    opponent_name = Column(String(255), nullable=True)  # NULL = bye
    table_number = Column(Integer, nullable=True)  # номер стола (пары); NULL = неизвестно
    player_wins = Column(Integer, nullable=True)  # победы игрока в матче; NULL = счёт неизвестен
    opponent_wins = Column(Integer, nullable=True)  # победы соперника в матче; NULL = счёт неизвестен

    __table_args__ = (UniqueConstraint("tournament_id", "round_number", "player_name", name="uq_round_pairing"),)


class RoundMatchStatus:
    """Persistence values for the peer-confirmed round result state machine."""

    UNREPORTED = "unreported"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ADMIN = "admin"
    IMPORTED = "imported"


class RoundMatch(Base):
    """One canonical match for a pair of reciprocal ``RoundPairing`` rows."""

    __tablename__ = "round_matches"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    round_number = Column(Integer, nullable=False)
    table_number = Column(Integer, nullable=True)
    pairing_key = Column(String(64), nullable=False)
    # Player order is the source/AetherHub order and is preserved in summaries.
    player1_name = Column(String(255), nullable=False)
    player2_name = Column(String(255), nullable=True)  # NULL = bye
    player1_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    player2_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    player1_wins = Column(Integer, nullable=True)
    player2_wins = Column(Integer, nullable=True)
    status = Column(String(16), nullable=False, default=RoundMatchStatus.UNREPORTED, server_default="unreported")
    proposed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    confirmed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revision = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    tournament = relationship("Tournament", back_populates="round_matches")
    player1_user = relationship("User", foreign_keys=[player1_user_id])
    player2_user = relationship("User", foreign_keys=[player2_user_id])
    events = relationship("RoundMatchEvent", back_populates="match", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("tournament_id", "round_number", "pairing_key", name="uq_round_match_pair"),
        CheckConstraint("player1_wins IS NULL OR player1_wins BETWEEN 0 AND 2", name="ck_round_match_p1_wins"),
        CheckConstraint("player2_wins IS NULL OR player2_wins BETWEEN 0 AND 2", name="ck_round_match_p2_wins"),
        CheckConstraint(
            "player1_wins IS NULL OR player2_wins IS NULL OR player1_wins <> 2 OR player2_wins <> 2",
            name="ck_round_match_not_2_2",
        ),
    )


class RoundMatchEvent(Base):
    """Append-only audit trail for proposals, confirmations, rejections and admin edits."""

    __tablename__ = "round_match_events"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("round_matches.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(24), nullable=False)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_tg_id = Column(BigInteger, nullable=True)
    player1_wins = Column(Integer, nullable=True)
    player2_wins = Column(Integer, nullable=True)
    revision = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    match = relationship("RoundMatch", back_populates="events")
    actor_user = relationship("User")


class MagicOculusImport(Base):
    """Состояние передачи одного турнира в Magic Oculus; защита от повторного POST."""

    __tablename__ = "magicoculus_imports"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(
        Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    aetherhub_url = Column(String(512), nullable=False, unique=True)
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    magicoculus_tournament_id = Column(Integer, nullable=True, unique=True)
    warnings_json = Column(String, nullable=True)
    error_json = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    imported_at = Column(DateTime, nullable=True)

    tournament = relationship("Tournament")


class TournamentCreationPlan(Base):
    """Отложенное ручное создание турнира и публикация регистрации в чат клуба."""

    __tablename__ = "tournament_creation_plans"

    id = Column(Integer, primary_key=True, index=True)
    club_name = Column(String(64), nullable=False, index=True)
    created_by_tg_id = Column(BigInteger, nullable=False, index=True)
    announce_at = Column(DateTime, nullable=False, index=True)
    event_at = Column(DateTime, nullable=False)
    announcement_chat_id = Column(BigInteger, nullable=True)
    announcement_chat_label = Column(
        String(255), nullable=False, default="не отправлять", server_default="не отправлять"
    )
    status = Column(String(16), nullable=False, default="pending", server_default="pending", index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id", ondelete="SET NULL"), nullable=True, unique=True)
    announcement_sent_at = Column(DateTime, nullable=True)
    last_error = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    tournament = relationship("Tournament")


class ClubAnnouncementSetting(Base):
    """Куда отправлять объявления о вручную создаваемых турнирах клуба."""

    __tablename__ = "club_announcement_settings"

    id = Column(Integer, primary_key=True, index=True)
    club_name = Column(String(64), nullable=False, unique=True, index=True)
    destination = Column(String(16), nullable=False, default="none", server_default="none")
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
