"""Сессия должна быть своя у каждой задачи, а не одна на поток.

Бот асинхронный и живёт в одном потоке: с ``scoped_session`` все задачи получали один и
тот же объект сессии, и ``db.close()`` в finally любой из них закрывал сессию соседям —
включая тех, кто в этот момент висел на await. Записи, сделанные после await, при этом
тихо терялись: объект оказывался detached, commit проходил вхолостую и без ошибки
(так пришёл дубль отбивки «сбор метагейма завершён», PR #169).

Тесты используют настоящую фабрику ``SessionLocal``, но с тестовым движком (``bind=``),
чтобы не зависеть от того, какая база прописана в окружении.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from core import models
from core.database import Base, SessionLocal


@pytest.fixture
def test_engine():
    """In-memory SQLite с одним общим соединением — иначе у каждой сессии была бы своя БД."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_each_call_returns_its_own_session(test_engine):
    first = SessionLocal(bind=test_engine)
    second = SessionLocal(bind=test_engine)
    try:
        assert first is not second
    finally:
        first.close()
        second.close()


def test_close_in_one_task_does_not_detach_objects_of_another(test_engine):
    """Соседняя задача закрыла свою сессию — наш объект остаётся живым и запись доходит."""
    mine = SessionLocal(bind=test_engine)
    neighbour = SessionLocal(bind=test_engine)
    try:
        user = models.User(tg_id=90001, first_name="Алиса")
        mine.add(user)
        mine.commit()
        loaded = mine.get(models.User, user.id)

        neighbour.close()  # ровно то, что делает finally соседнего хендлера

        loaded.username = "alice"
        mine.commit()

        assert mine.get(models.User, user.id).username == "alice"
    finally:
        mine.close()
        neighbour.close()


def test_two_sessions_see_each_others_commits(test_engine):
    """Разные сессии — это по-прежнему одна база: закоммиченное одной видно другой."""
    writer = SessionLocal(bind=test_engine)
    reader = SessionLocal(bind=test_engine)
    try:
        writer.add(models.User(tg_id=90002, first_name="Боб"))
        writer.commit()

        assert reader.query(models.User).filter_by(tg_id=90002).one().first_name == "Боб"
    finally:
        writer.close()
        reader.close()
