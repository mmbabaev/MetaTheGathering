"""Tests for /settings handler and UserService methods."""

import pytest
from core.schemas import TournamentCreate
from bot.handlers.settings import handle_settings, handle_settings_name_text
from bot.messages import SETTINGS_MENU, NAME_SAVED


# --- UserService.update_name ---

class TestUpdateUserName:
    def test_creates_user_if_not_exists(self, user_svc):
        user = user_svc.update_name(tg_id=9001, first_name="Иван", last_name="Иванов")
        assert user.first_name == "Иван"
        assert user.last_name == "Иванов"
        assert user.tg_id == 9001

    def test_updates_existing_user(self, user_svc):
        user_svc.get_or_create(tg_id=9002, username="user", first_name="Старое")
        user = user_svc.update_name(tg_id=9002, first_name="Новое", last_name="Имя")
        assert user.first_name == "Новое"
        assert user.last_name == "Имя"

    def test_clears_last_name_when_none(self, user_svc):
        user_svc.update_name(tg_id=9003, first_name="Иван", last_name="Иванов")
        user = user_svc.update_name(tg_id=9003, first_name="Иван", last_name=None)
        assert user.last_name is None

    def test_strips_whitespace(self, user_svc):
        user = user_svc.update_name(tg_id=9004, first_name="  Иван  ", last_name="  Иванов  ")
        assert user.first_name == "Иван"
        assert user.last_name == "Иванов"


# --- UserService.get_by_tg_id ---

class TestGetUserByTgId:
    def test_returns_user(self, user_svc):
        user_svc.get_or_create(tg_id=9010, username="x", first_name="X")
        user = user_svc.get_by_tg_id(9010)
        assert user is not None
        assert user.tg_id == 9010

    def test_returns_none_for_unknown(self, user_svc):
        assert user_svc.get_by_tg_id(99999) is None


# --- handle_settings ---

class TestHandleSettings:
    def test_no_user_shows_not_set(self, db):
        result = handle_settings(db, tg_id=8001)
        assert SETTINGS_MENU in result.text
        assert "не указано" in result.text
        assert result.keyboard is not None

    def test_user_with_name_shows_name(self, db, user_svc):
        user_svc.update_name(tg_id=8002, first_name="Иван", last_name="Иванов")
        result = handle_settings(db, tg_id=8002)
        assert "Иван" in result.text
        assert "Иванов" in result.text

    def test_user_with_first_name_only(self, db, user_svc):
        user_svc.update_name(tg_id=8003, first_name="Мария")
        result = handle_settings(db, tg_id=8003)
        assert "Мария" in result.text

    def test_returns_keyboard(self, db):
        result = handle_settings(db, tg_id=8004)
        assert result.keyboard is not None


# --- handle_settings_name_text ---

class TestHandleSettingsNameText:
    def test_saves_first_name_only(self, db, user_svc):
        user_svc.get_or_create(tg_id=8010, username="u", first_name="Old")
        result = handle_settings_name_text(db, tg_id=8010, name_text="Новое")
        assert "Новое" in result.text
        user = user_svc.get_by_tg_id(8010)
        assert user.first_name == "Новое"
        assert user.last_name is None

    def test_saves_first_and_last_name(self, db, user_svc):
        user_svc.get_or_create(tg_id=8011, username="u", first_name="Old")
        result = handle_settings_name_text(db, tg_id=8011, name_text="Иван Петров")
        assert "Иван" in result.text
        assert "Петров" in result.text
        user = user_svc.get_by_tg_id(8011)
        assert user.first_name == "Иван"
        assert user.last_name == "Петров"

    def test_returns_name_saved_message(self, db):
        result = handle_settings_name_text(db, tg_id=8012, name_text="Анна")
        assert result.text == NAME_SAVED.format(full_name="Анна")
