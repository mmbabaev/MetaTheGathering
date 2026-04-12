import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from core.database import Base
import core.models  # noqa: F401 — регистрирует все модели на Base.metadata
from core.models import TournamentStatus, VoteType
from core.schemas import TournamentCreate
from services.tournament import TournamentService
from services.user import UserService


@pytest.fixture
def db():
    """Чистая in-memory SQLite сессия на каждый тест."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # Включаем FK-ограничения в SQLite (по умолчанию отключены)
    @event.listens_for(engine, "connect")
    def set_fk_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def svc(db):
    return TournamentService(db)


@pytest.fixture
def user_svc(db):
    return UserService(db)


@pytest.fixture
def tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Test Tournament", chat_id=100, slug="test"))


@pytest.fixture
def user_alice(user_svc):
    return user_svc.get_or_create(tg_id=1001, username="alice", first_name="Alice")


@pytest.fixture
def user_bob(user_svc):
    return user_svc.get_or_create(tg_id=1002, username="bob", first_name="Bob")


@pytest.fixture
def archetype_burn(svc):
    return svc.get_or_create_archetype_by_name("Burn")


@pytest.fixture
def archetype_affinity(svc):
    return svc.get_or_create_archetype_by_name("Affinity")
