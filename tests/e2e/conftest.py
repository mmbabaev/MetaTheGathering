import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import core.models  # noqa: F401
from core.database import Base
from core.schemas import TournamentCreate
from services.aetherhub_models import AetherhubPairing, AetherhubRound, AetherhubTournamentData
from services.tournament import TournamentService

CHAT_ID = -1003631429183  # debug config chat_id


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

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
def tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Pauper Friday #99", chat_id=CHAT_ID))


@pytest.fixture
def aetherhub_data():
    """Fixture tournament data with 4 players and 2 rounds."""
    return AetherhubTournamentData(
        url="https://aetherhub.com/Tourney/RoundTourney/99291",
        players=["Иван Иванов", "Пётр Петров", "Сидор Сидоров", "Анна Смирнова"],
        rounds=[
            AetherhubRound(
                number=1,
                pairings=[
                    AetherhubPairing(player="Иван Иванов", opponent="Пётр Петров"),
                    AetherhubPairing(player="Пётр Петров", opponent="Иван Иванов"),
                    AetherhubPairing(player="Сидор Сидоров", opponent="Анна Смирнова"),
                    AetherhubPairing(player="Анна Смирнова", opponent="Сидор Сидоров"),
                ],
            ),
            AetherhubRound(
                number=2,
                pairings=[
                    AetherhubPairing(player="Иван Иванов", opponent="Сидор Сидоров"),
                    AetherhubPairing(player="Сидор Сидоров", opponent="Иван Иванов"),
                    AetherhubPairing(player="Пётр Петров", opponent="Анна Смирнова"),
                    AetherhubPairing(player="Анна Смирнова", opponent="Пётр Петров"),
                ],
            ),
        ],
        standings=["Иван Иванов", "Сидор Сидоров", "Пётр Петров", "Анна Смирнова"],
    )
