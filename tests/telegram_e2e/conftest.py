import socket

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base


@pytest.fixture(autouse=True)
def forbid_external_state(monkeypatch):
    """Fail before an E2E test can reach a network or a persistent database."""
    database_url = settings.DATABASE_URL.unicode_string()
    assert database_url.startswith("sqlite") and ":memory:" in database_url
    assert settings.TELEGRAM_BOT_TOKEN in {
        "TEST_TOKEN",
        "0000000000:test_token_for_ci",
        "0000000000:dummy-not-a-real-key",
    }

    def blocked_connect(*_args, **_kwargs):
        raise AssertionError("Network access is forbidden in in-process Telegram E2E tests")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)


@pytest.fixture
def isolated_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()
