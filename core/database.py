from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base

from core.config import settings

engine = create_engine(
    settings.DATABASE_URL.unicode_string(),  # pydantic AnyUrl → str
    echo=settings.DEBUG,
    future=True,
)

SessionLocal = scoped_session(
    sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        future=True,
    )
)

Base = declarative_base()


def get_db():
    """Заготовка для DI (FastAPI / хендлеры бота)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
