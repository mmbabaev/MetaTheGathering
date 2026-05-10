from contextlib import contextmanager

from core.database import SessionLocal


@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
