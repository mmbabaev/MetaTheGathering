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
    notify_poll = Column(
        Boolean, default=False, nullable=False, server_default="false"
    )  # опт-ин на уведомления о голосованиях
    status_by_pairings = Column(Boolean, default=False, nullable=False)  # статус турнира попарно по парингам

    created_at = Column(DateTime, default=utc_now, nullable=False)

    participants = relationship("Participant", back_populates="user", cascade="all, delete-orphan")
    votes = relationship("Vote", back_populates="voter", cascade="all, delete-orphan")
    deck_history = relationship("UserDeckHistory", back_populates="user", cascade="all, delete-orphan")
    web_auth_tokens = relationship("WebAuthToken", back_populates="user", cascade="all, delete-orphan")


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

    registration_open_at = Column(DateTime, nullable=True)
    registration_close_at = Column(DateTime, nullable=True)

    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)

    decks_hidden = Column(Boolean, nullable=False, default=True, server_default="true")
    aetherhub_url = Column(String(512), nullable=True)
    aetherhub_import_time = Column(String(5), nullable=True)  # "HH:MM" — scheduled auto-import time

    # момент отправки анонса «сбор метагейма завершён»; NULL = ещё не анонсировали (идемпотентность)
    completed_announced_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)

    participants = relationship("Participant", back_populates="tournament", cascade="all, delete-orphan")
    votes = relationship("Vote", back_populates="tournament", cascade="all, delete-orphan")
    poll = relationship("TournamentPoll", back_populates="tournament", uselist=False, cascade="all, delete-orphan")


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

    final_place = Column(Integer, nullable=True)  # место в финальных стендингах; NULL = не импортировано

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
