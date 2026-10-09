"""Shared resource-management helpers for Telegram adapters."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from core.database import SessionLocal

SessionFactory = Callable[[], Session]


@contextmanager
def db_session(session_factory: SessionFactory = SessionLocal) -> Iterator[Session]:
    """Open one database session for a Telegram callback and always close it.

    ``session_factory`` is explicit so wrapper tests can keep patching the local
    ``SessionLocal`` symbol without coupling themselves to this module.
    """

    db = session_factory()
    try:
        yield db
    finally:
        db.close()
