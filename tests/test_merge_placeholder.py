"""Tests for UserService.merge_placeholder_by_name — linking real tg users to placeholder deck history."""

import pytest
from sqlalchemy import select

from core import models
from core.schemas import TournamentCreate
from services.archetype import ArchetypeService
from services.tournament import TournamentService
from services.user import UserService

REAL_TG_ID = 555_000


@pytest.fixture
def placeholder(db):
    """Placeholder user (bulk-added, no tg_id) with deck history."""
    arch = ArchetypeService(db).get_or_create_by_name("Burn")
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
        histories = (
            db.execute(select(models.UserDeckHistory).where(models.UserDeckHistory.user_id == real_user.id))
            .scalars()
            .all()
        )
        assert len(histories) == 1

    def test_placeholder_deleted(self, db, placeholder, real_user):
        svc = UserService(db)
        svc.merge_placeholder_by_name(REAL_TG_ID, "Сергей", "Крипков")
        gone = db.execute(select(models.User).where(models.User.id == placeholder.id)).scalar_one_or_none()
        assert gone is None

    def test_swapped_name_order(self, db, placeholder, real_user):
        svc = UserService(db)
        merged = svc.merge_placeholder_by_name(REAL_TG_ID, "Крипков", "Сергей")
        assert merged is True

    def test_full_name_in_single_telegram_field_matches_split_placeholder(self, db, placeholder):
        real = models.User(tg_id=REAL_TG_ID, first_name="Сергей Крипков", last_name=None)
        db.add(real)
        db.commit()
        merged = UserService(db).merge_placeholder_by_name(REAL_TG_ID, "Сергей Крипков", None)
        assert merged is True
        assert db.get(models.User, placeholder.id) is None

    def test_swapped_name_adopts_canonical_form(self, db, placeholder, real_user):
        """Если пользователь ввёл имя в обратном порядке (Имя Фамилия вместо Фамилия Имя),
        после слияния его имя исправляется по плейсхолдеру."""
        svc = UserService(db)
        # real_user already has wrong order set (as if they typed "Сергей Крипков")
        real_user.first_name = "Крипков"
        real_user.last_name = "Сергей"
        db.commit()

        svc.merge_placeholder_by_name(REAL_TG_ID, "Крипков", "Сергей")

        db.refresh(real_user)
        assert real_user.first_name == "Сергей"  # placeholder's first_name
        assert real_user.last_name == "Крипков"  # placeholder's last_name

    def test_no_placeholder_returns_false(self, db, real_user):
        svc = UserService(db)
        result = svc.merge_placeholder_by_name(REAL_TG_ID, "Неизвестный", "Игрок")
        assert result is False

    def test_real_user_not_merged_with_another_real(self, db):
        user_svc = UserService(db)
        user_svc.get_or_create(tg_id=111, first_name="Иван", last_name="Петров")
        user_svc.get_or_create(tg_id=222, username="test")
        result = user_svc.merge_placeholder_by_name(222, "Иван", "Петров")
        assert result is False  # u1 has positive tg_id — not a placeholder

    def test_participants_transferred(self, db, placeholder, arch_svc):
        """Участие в прошлых турнирах переходит к реальному пользователю."""
        tsvc = TournamentService(db)
        usvc = UserService(db)
        arch = arch_svc.get_or_create_by_name("Burn")
        t = tsvc.create_tournament(TournamentCreate(title="Old tourney", chat_id=1, slug="old"))
        part = models.Participant(tournament_id=t.id, user_id=placeholder.id, archetype_id=arch.id)
        db.add(part)
        db.commit()

        real = models.User(tg_id=REAL_TG_ID, username="khripkovsergey")
        db.add(real)
        db.commit()

        usvc.merge_placeholder_by_name(REAL_TG_ID, "Сергей", "Крипков")

        participants = (
            db.execute(select(models.Participant).where(models.Participant.user_id == real.id)).scalars().all()
        )
        assert len(participants) == 1

    def test_no_duplicate_participants_on_conflict(self, db, placeholder, arch_svc):
        """Если реальный юзер уже зарегистрирован на тот же турнир — дубликат не создаётся."""
        tsvc = TournamentService(db)
        usvc = UserService(db)
        arch = arch_svc.get_or_create_by_name("Burn")
        t = tsvc.create_tournament(TournamentCreate(title="Same tourney", chat_id=1, slug="same"))

        real = models.User(tg_id=REAL_TG_ID)
        db.add(real)
        db.flush()
        # Both registered for same tournament
        db.add(models.Participant(tournament_id=t.id, user_id=placeholder.id, archetype_id=arch.id))
        db.add(models.Participant(tournament_id=t.id, user_id=real.id, archetype_id=arch.id))
        db.commit()

        usvc.merge_placeholder_by_name(REAL_TG_ID, "Сергей", "Крипков")

        participants = (
            db.execute(select(models.Participant).where(models.Participant.user_id == real.id)).scalars().all()
        )
        assert len(participants) == 1  # без дублей
