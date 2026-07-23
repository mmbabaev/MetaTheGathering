"""Тесты AppStatsService и AppStatsHandler — /app_statistics (только владелец)."""

from unittest.mock import patch

import pytest

from bot.handlers.app_stats import NOT_OWNER, AppStatsHandler
from bot.keyboards import CB_APP_STATS_NOTIFY_ROUNDS, Keyboards
from services.app_stats import AppStatsService
from services.user import UserService

OWNER_TG_ID = 232778570


@pytest.fixture
def stats_svc(db):
    return AppStatsService(db)


@pytest.fixture
def handler(db):
    return AppStatsHandler(AppStatsService(db), Keyboards())


@pytest.fixture(autouse=True)
def _owner(monkeypatch):
    # Владелец фиксирован для тестов, не зависит от локального конфига.
    monkeypatch.setattr("bot.handlers.app_stats.settings.OWNER_CHAT_ID", OWNER_TG_ID)


def _user(db, tg_id, notify, first=None, username=None):
    u = UserService(db).get_or_create(tg_id=tg_id, username=username, first_name=first)
    u.notify_opponent_rounds = notify
    db.commit()
    return u


class TestNotifyRoundsQueries:
    def test_count_only_enabled_real_users(self, stats_svc, db):
        _user(db, 1001, notify=True, first="A")
        _user(db, 1002, notify=True, first="B")
        _user(db, 1003, notify=False, first="C")
        # плейсхолдер (tg_id<0) с включённым флагом не считается
        ph, _ = UserService(db).get_or_create_by_name("Плейс", "Холдер")
        ph.notify_opponent_rounds = True
        db.commit()
        assert stats_svc.notify_rounds_count() == 2

    def test_users_sorted_by_name(self, stats_svc, db):
        _user(db, 1001, notify=True, first="Яков")
        _user(db, 1002, notify=True, first="Анна")
        names = [u.first_name for u in stats_svc.notify_rounds_users()]
        assert names == ["Анна", "Яков"]

    def test_empty(self, stats_svc):
        assert stats_svc.notify_rounds_count() == 0
        assert stats_svc.notify_rounds_users() == []


class TestHandlerOwnerGate:
    def test_home_denied_for_non_owner(self, handler):
        result = handler.handle_home(tg_id=999)
        assert NOT_OWNER in result.text
        assert result.keyboard is None

    def test_list_denied_for_non_owner(self, handler):
        result = handler.handle_notify_rounds_list(tg_id=999)
        assert result.is_alert
        assert NOT_OWNER in result.text

    def test_home_shows_count_for_owner(self, handler, db):
        _user(db, 1001, notify=True, first="A")
        result = handler.handle_home(OWNER_TG_ID)
        button = result.keyboard.inline_keyboard[0][0]
        assert "1" in button.text
        assert button.callback_data == CB_APP_STATS_NOTIFY_ROUNDS

    def test_list_shows_users_for_owner(self, handler, db):
        _user(db, 1001, notify=True, first="Иван", username="ivan")
        result = handler.handle_notify_rounds_list(OWNER_TG_ID)
        assert "@ivan" in result.text
        assert "Иван" in result.text
        assert "включили 1" in result.text

    def test_list_empty_for_owner(self, handler):
        result = handler.handle_notify_rounds_list(OWNER_TG_ID)
        assert "включили 0" in result.text
        assert "пока никто" in result.text


class TestOwnerNone:
    def test_no_owner_configured_denies(self, handler):
        with patch("bot.handlers.app_stats.settings.OWNER_CHAT_ID", None):
            result = handler.handle_home(OWNER_TG_ID)
        assert NOT_OWNER in result.text
