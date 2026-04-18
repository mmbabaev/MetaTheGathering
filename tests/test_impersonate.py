"""Tests for impersonation feature: ImpersonationState + AdminHandler methods."""

import pytest
from sqlalchemy.orm import Session

from core.impersonate import ImpersonationState
from bot.handlers.admin import AdminHandler
from bot.messages import NOT_ADMIN
from services.tournament import TournamentService
from services.user import UserService

ADMIN_TG_ID = 9001
USER_TG_ID = 1001
USER2_TG_ID = 1002


@pytest.fixture
def state() -> ImpersonationState:
    return ImpersonationState()


@pytest.fixture
def admin_user(user_svc, svc):
    u = user_svc.get_or_create(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin")
    from sqlalchemy import select
    from core import models
    obj = svc.db.execute(select(models.User).where(models.User.tg_id == ADMIN_TG_ID)).scalar_one()
    obj.is_admin = True
    svc.db.commit()
    return u


@pytest.fixture
def target_user(user_svc):
    return user_svc.get_or_create(tg_id=USER_TG_ID, username="alice", first_name="Alice", last_name="Smith")


@pytest.fixture
def target_user2(user_svc):
    return user_svc.get_or_create(tg_id=USER2_TG_ID, first_name="Иван", last_name="Петров")


@pytest.fixture
def handler(svc, user_svc) -> AdminHandler:
    return AdminHandler(svc, user_svc)


class TestImpersonationState:
    def test_initial_no_impersonation(self, state):
        assert state.get_acting_tg_id(ADMIN_TG_ID) == ADMIN_TG_ID
        assert not state.is_impersonating(ADMIN_TG_ID)

    def test_set_returns_target(self, state):
        state.set(ADMIN_TG_ID, USER_TG_ID)
        assert state.get_acting_tg_id(ADMIN_TG_ID) == USER_TG_ID

    def test_clear_restores_self(self, state):
        state.set(ADMIN_TG_ID, USER_TG_ID)
        state.clear(ADMIN_TG_ID)
        assert state.get_acting_tg_id(ADMIN_TG_ID) == ADMIN_TG_ID
        assert not state.is_impersonating(ADMIN_TG_ID)

    def test_non_impersonating_user_unaffected(self, state):
        state.set(ADMIN_TG_ID, USER_TG_ID)
        assert state.get_acting_tg_id(USER2_TG_ID) == USER2_TG_ID

    def test_get_target(self, state):
        state.set(ADMIN_TG_ID, USER_TG_ID)
        assert state.get_target(ADMIN_TG_ID) == USER_TG_ID
        assert state.get_target(USER_TG_ID) is None

    def test_instances_are_independent(self):
        s1 = ImpersonationState()
        s2 = ImpersonationState()
        s1.set(ADMIN_TG_ID, USER_TG_ID)
        assert not s2.is_impersonating(ADMIN_TG_ID)


class TestHandleImpersonate:
    def test_non_admin_rejected(self, handler, state, target_user):
        result = handler.handle_impersonate(USER_TG_ID, "alice", state)
        assert NOT_ADMIN in result.text
        assert not state.is_impersonating(USER_TG_ID)

    def test_by_username(self, handler, state, admin_user, target_user):
        result = handler.handle_impersonate(ADMIN_TG_ID, "@alice", state)
        assert "Alice" in result.text
        assert state.get_acting_tg_id(ADMIN_TG_ID) == USER_TG_ID

    def test_by_username_without_at(self, handler, state, admin_user, target_user):
        result = handler.handle_impersonate(ADMIN_TG_ID, "alice", state)
        assert state.get_acting_tg_id(ADMIN_TG_ID) == USER_TG_ID

    def test_by_full_name(self, handler, state, admin_user, target_user2):
        result = handler.handle_impersonate(ADMIN_TG_ID, "Иван Петров", state)
        assert state.get_acting_tg_id(ADMIN_TG_ID) == USER2_TG_ID

    def test_unknown_username_creates_placeholder(self, handler, state, admin_user):
        result = handler.handle_impersonate(ADMIN_TG_ID, "@newuser", state)
        assert "placeholder" in result.text
        assert state.is_impersonating(ADMIN_TG_ID)
        assert state.get_acting_tg_id(ADMIN_TG_ID) < 0

    def test_unknown_name_creates_placeholder(self, handler, state, admin_user):
        result = handler.handle_impersonate(ADMIN_TG_ID, "Новый Игрок", state)
        assert "placeholder" in result.text
        assert state.is_impersonating(ADMIN_TG_ID)
        assert state.get_acting_tg_id(ADMIN_TG_ID) < 0


class TestHandleStopImpersonate:
    def test_stop_when_not_impersonating(self, handler, state, admin_user):
        result = handler.handle_stop_impersonate(ADMIN_TG_ID, state)
        assert "не в режиме" in result.text.lower()

    def test_stop_clears_state(self, handler, state, admin_user, target_user):
        state.set(ADMIN_TG_ID, USER_TG_ID)
        result = handler.handle_stop_impersonate(ADMIN_TG_ID, state)
        assert not state.is_impersonating(ADMIN_TG_ID)
        assert "отключён" in result.text

    def test_non_admin_rejected(self, handler, state):
        state.set(USER_TG_ID, USER2_TG_ID)
        result = handler.handle_stop_impersonate(USER_TG_ID, state)
        assert NOT_ADMIN in result.text
