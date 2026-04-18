"""Tests for UserService.merge_placeholder_by_name — linking real tg users to placeholder deck history."""

import pytest
from sqlalchemy import select

from core import models
from services.user import UserService
from services.tournament import TournamentService
from core.schemas import TournamentCreate

REAL_TG_ID = 555_000


@pytest.fixture
def placeholder(db):
    """Placeholder user (bulk-added, no tg_id) with deck history."""
    svc = TournamentService(db)
    arch = svc.get_or_create_archetype_by_name("Burn")
    user = models.User(tg_id=-1, first_name="Сергей", last_name="Крипков")
    db.add(user)
    db.flush()
    db.add(models.UserDeckHistory(user_id=user.id, archetype_id=arch.id, source="datalens"))
    db.commit()
    return user


@pytest.fixture
def real_user(db):
    """Real Telegram user, no name yet."""
    user = models.User(tg_id=REAL_TG_ID, username="khripkovsergey")
    db.add(user)
    db.commit()
    return user


class TestMergePlaceholderByName:
    def test_deck_history_transferred(self, db, placeholder, real_user):
        svc = UserService(db)
        merged = svc.merge_placeholder_by_name(REAL_TG_ID, "Сергей", "Крипков")
        assert merged is True
        histories = db.execute(
            select(models.UserDeckHistory).where(models.UserDeckHistory.user_id == real_user.id)
        ).scalars().all()
        assert len(histories) == 1

    def test_placeholder_deleted(self, db, placeholder, real_user):
        svc = UserService(db)
        svc.merge_placeholder_by_name(REAL_TG_ID, "Сергей", "Крипков")
        gone = db.execute(
            select(models.User).where(models.User.id == placeholder.id)
        ).scalar_one_or_none()
        assert gone is None

    def test_swapped_name_order(self, db, placeholder, real_user):
        svc = UserService(db)
        merged = svc.merge_placeholder_by_name(REAL_TG_ID, "Крипков", "Сергей")
        assert merged is True

    def test_no_placeholder_returns_false(self, db, real_user):
        svc = UserService(db)
        result = svc.merge_placeholder_by_name(REAL_TG_ID, "Неизвестный", "Игрок")
        assert result is False

    def test_real_user_not_merged_with_another_real(self, db):
        user_svc = UserService(db)
        u1 = user_svc.get_or_create(tg_id=111, first_name="Иван", last_name="Петров")
        u2 = user_svc.get_or_create(tg_id=222, username="test")
        result = user_svc.merge_placeholder_by_name(222, "Иван", "Петров")
        assert result is False  # u1 has positive tg_id — not a placeholder

    def test_participants_transferred(self, db, placeholder):
        """Участие в прошлых турнирах переходит к реальному пользователю."""
        tsvc = TournamentService(db)
        usvc = UserService(db)
        arch = tsvc.get_or_create_archetype_by_name("Burn")
        t = tsvc.create_tournament(TournamentCreate(title="Old tourney", chat_id=1, slug="old"))
        part = models.Participant(tournament_id=t.id, user_id=placeholder.id, archetype_id=arch.id)
        db.add(part)
        db.commit()

        real = models.User(tg_id=REAL_TG_ID, username="khripkovsergey")
        db.add(real)
        db.commit()

        usvc.merge_placeholder_by_name(REAL_TG_ID, "Сергей", "Крипков")

        participants = db.execute(
            select(models.Participant).where(models.Participant.user_id == real.id)
        ).scalars().all()
        assert len(participants) == 1

    def test_no_duplicate_participants_on_conflict(self, db, placeholder):
        """Если реальный юзер уже зарегистрирован на тот же турнир — дубликат не создаётся."""
        tsvc = TournamentService(db)
        usvc = UserService(db)
        arch = tsvc.get_or_create_archetype_by_name("Burn")
        t = tsvc.create_tournament(TournamentCreate(title="Same tourney", chat_id=1, slug="same"))

        real = models.User(tg_id=REAL_TG_ID)
        db.add(real)
        db.flush()
        # Both registered for same tournament
        db.add(models.Participant(tournament_id=t.id, user_id=placeholder.id, archetype_id=arch.id))
        db.add(models.Participant(tournament_id=t.id, user_id=real.id, archetype_id=arch.id))
        db.commit()

        usvc.merge_placeholder_by_name(REAL_TG_ID, "Сергей", "Крипков")

        participants = db.execute(
            select(models.Participant).where(models.Participant.user_id == real.id)
        ).scalars().all()
        assert len(participants) == 1  # без дублей
