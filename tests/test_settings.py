"""Tests for /settings handler and UserService methods."""

import pytest

from bot.handlers.settings import SettingsHandler
from bot.keyboards import Keyboards
from bot.messages import NAME_SAVED, SETTINGS_MENU


@pytest.fixture
def handler(user_svc):
    return SettingsHandler(user_svc)


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
    def test_no_user_shows_not_set(self, handler):
        result = handler.handle_settings(tg_id=8001)
        assert SETTINGS_MENU in result.text
        assert "не указано" in result.text
        assert result.keyboard is not None

    def test_user_with_name_shows_name(self, handler, user_svc):
        user_svc.update_name(tg_id=8002, first_name="Иван", last_name="Иванов")
        result = handler.handle_settings(tg_id=8002)
        assert "Иван" in result.text
        assert "Иванов" in result.text

    def test_user_with_first_name_only(self, handler, user_svc):
        user_svc.update_name(tg_id=8003, first_name="Мария")
        result = handler.handle_settings(tg_id=8003)
        assert "Мария" in result.text

    def test_returns_keyboard(self, handler):
        result = handler.handle_settings(tg_id=8004)
        assert result.keyboard is not None


# --- handle_settings_name_text ---


class TestHandleSettingsNameText:
    def test_saves_first_name_only(self, handler, user_svc):
        user_svc.get_or_create(tg_id=8010, username="u", first_name="Old")
        result = handler.handle_settings_name_text(tg_id=8010, name_text="Новое")
        assert "Новое" in result.text
        user = user_svc.get_by_tg_id(8010)
        assert user.first_name == "Новое"
        assert user.last_name is None

    def test_saves_first_and_last_name(self, handler, user_svc):
        user_svc.get_or_create(tg_id=8011, username="u", first_name="Old")
        result = handler.handle_settings_name_text(tg_id=8011, name_text="Петров Иван")
        assert "Иван" in result.text
        assert "Петров" in result.text
        user = user_svc.get_by_tg_id(8011)
        assert user.first_name == "Иван"
        assert user.last_name == "Петров"

    def test_returns_name_saved_message(self, handler):
        result = handler.handle_settings_name_text(tg_id=8012, name_text="Анна")
        assert result.text == NAME_SAVED.format(full_name="Анна")


# --- UserService.toggle_hide_deck_emoji ---


class TestToggleHideDeckEmoji:
    def test_default_is_false(self, user_svc):
        user_svc.get_or_create(tg_id=9100, username="u", first_name="X")
        user = user_svc.get_by_tg_id(9100)
        assert user.hide_deck_emoji is False

    def test_toggle_enables(self, user_svc):
        user_svc.get_or_create(tg_id=9101, username="u", first_name="X")
        new_val = user_svc.toggle_hide_deck_emoji(9101)
        assert new_val is True
        assert user_svc.get_by_tg_id(9101).hide_deck_emoji is True

    def test_toggle_disables(self, user_svc):
        user_svc.get_or_create(tg_id=9102, username="u", first_name="X")
        user_svc.toggle_hide_deck_emoji(9102)
        new_val = user_svc.toggle_hide_deck_emoji(9102)
        assert new_val is False

    def test_toggle_unknown_user_returns_false(self, user_svc):
        assert user_svc.toggle_hide_deck_emoji(99999) is False


# --- handle_toggle_emoji ---


class TestHandleToggleEmoji:
    def test_toggles_flag_and_returns_settings(self, handler, user_svc):
        user_svc.get_or_create(tg_id=9110, username="u", first_name="X")
        result = handler.handle_toggle_emoji(tg_id=9110)
        assert SETTINGS_MENU in result.text
        assert user_svc.get_by_tg_id(9110).hide_deck_emoji is True

    def test_keyboard_reflects_hidden_state(self, handler, user_svc):
        user_svc.get_or_create(tg_id=9111, username="u", first_name="X")
        handler.handle_toggle_emoji(tg_id=9111)  # now hidden
        result = handler.handle_settings(tg_id=9111)
        buttons_text = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert any("выкл" in t for t in buttons_text)

    def test_keyboard_reflects_shown_state(self, handler, user_svc):
        user_svc.get_or_create(tg_id=9112, username="u", first_name="X")
        result = handler.handle_settings(tg_id=9112)
        buttons_text = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert any("вкл" in t for t in buttons_text)


# --- UserService.toggle_notify_opponent_rounds ---


class TestToggleNotifyOpponentRounds:
    def test_default_is_false(self, user_svc):
        user_svc.get_or_create(tg_id=9200, username="u", first_name="X")
        user = user_svc.get_by_tg_id(9200)
        assert user.notify_opponent_rounds is False

    def test_toggle_enables(self, user_svc):
        user_svc.get_or_create(tg_id=9201, username="u", first_name="X")
        new_val = user_svc.toggle_notify_opponent_rounds(9201)
        assert new_val is True
        assert user_svc.get_by_tg_id(9201).notify_opponent_rounds is True

    def test_toggle_disables(self, user_svc):
        user_svc.get_or_create(tg_id=9202, username="u", first_name="X")
        user_svc.toggle_notify_opponent_rounds(9202)
        new_val = user_svc.toggle_notify_opponent_rounds(9202)
        assert new_val is False

    def test_toggle_unknown_user_returns_false(self, user_svc):
        assert user_svc.toggle_notify_opponent_rounds(99999) is False

    def test_wants_notifications_reflects_flag(self, user_svc):
        user_svc.get_or_create(tg_id=9203, username="u", first_name="X")
        assert user_svc.wants_opponent_notifications(9203) is False
        user_svc.toggle_notify_opponent_rounds(9203)
        assert user_svc.wants_opponent_notifications(9203) is True

    def test_wants_notifications_unknown_user_false(self, user_svc):
        assert user_svc.wants_opponent_notifications(99999) is False


class TestToggleNotifyAchievements:
    def test_requires_explicit_opt_in_and_can_be_disabled(self, user_svc):
        user_svc.get_or_create(tg_id=9250, username="u", first_name="X")
        assert user_svc.wants_achievement_notifications(9250) is False
        assert user_svc.toggle_notify_achievements(9250) is True
        assert user_svc.wants_achievement_notifications(9250) is True
        assert user_svc.toggle_notify_achievements(9250) is False

    def test_handler_exposes_achievement_toggle(self, handler, user_svc):
        user_svc.get_or_create(tg_id=9251, username="u", first_name="X")
        result = handler.handle_toggle_achievements_notify(9251)
        labels = [button.text for row in result.keyboard.inline_keyboard for button in row]
        assert any("Уведомления об ачивках: вкл" in label for label in labels)


# --- handle_toggle_opponent_notify ---


class TestHandleToggleOpponentNotify:
    def test_toggles_flag_and_returns_settings(self, handler, user_svc):
        user_svc.get_or_create(tg_id=9210, username="u", first_name="X")
        result = handler.handle_toggle_opponent_notify(tg_id=9210)
        assert SETTINGS_MENU in result.text
        assert user_svc.get_by_tg_id(9210).notify_opponent_rounds is True

    def test_keyboard_reflects_enabled_state(self, handler, user_svc):
        user_svc.get_or_create(tg_id=9211, username="u", first_name="X")
        handler.handle_toggle_opponent_notify(tg_id=9211)  # now enabled
        result = handler.handle_settings(tg_id=9211)
        buttons_text = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert any("Уведомления об оппоненте: вкл" in t for t in buttons_text)

    def test_keyboard_reflects_disabled_state_by_default(self, handler, user_svc):
        user_svc.get_or_create(tg_id=9212, username="u", first_name="X")
        result = handler.handle_settings(tg_id=9212)
        buttons_text = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert any("Уведомления об оппоненте: выкл" in t for t in buttons_text)


# --- emoji in archetype keyboards ---


class TestArchetypeKeyboardEmoji:
    def test_show_emoji_true_includes_emoji(self):
        kb = Keyboards()
        archetypes = [(1, "Red Kuldotha"), (2, "Blue Delver")]
        result = kb.archetype_keyboard(tournament_id=1, archetypes=archetypes, show_emoji=True)
        labels = [b.text for row in result.inline_keyboard for b in row]
        assert any("🔴" in t for t in labels)

    def test_show_emoji_false_no_emoji(self):
        kb = Keyboards()
        archetypes = [(1, "Red Kuldotha"), (2, "Blue Delver")]
        result = kb.archetype_keyboard(tournament_id=1, archetypes=archetypes, show_emoji=False)
        labels = [b.text for row in result.inline_keyboard for b in row]
        assert all("🔴" not in t and "🔵" not in t for t in labels)
        assert any(t == "Red Kuldotha" for t in labels)

    def test_admin_keyboard_show_emoji_false(self):
        kb = Keyboards()
        archetypes = [(1, "Red Kuldotha")]
        result = kb.admin_archetype_select_keyboard(participant_id=1, archetypes=archetypes, show_emoji=False)
        labels = [b.text for row in result.inline_keyboard for b in row]
        assert any(t == "Red Kuldotha" for t in labels)
        assert all("🔴" not in t for t in labels)


# --- UserService.toggle_notify_poll (опт-ин на уведомления о голосованиях) ---


class TestToggleNotifyPoll:
    def test_default_is_false(self, user_svc):
        user_svc.get_or_create(tg_id=9300, username="u", first_name="X")
        assert user_svc.get_by_tg_id(9300).notify_poll is False
        assert user_svc.wants_poll_notifications(9300) is False

    def test_toggle_enables_and_disables(self, user_svc):
        user_svc.get_or_create(tg_id=9301, username="u", first_name="X")
        assert user_svc.toggle_notify_poll(9301) is True
        assert user_svc.wants_poll_notifications(9301) is True
        assert user_svc.toggle_notify_poll(9301) is False

    def test_toggle_unknown_user_returns_false(self, user_svc):
        assert user_svc.toggle_notify_poll(99999) is False
        assert user_svc.wants_poll_notifications(99999) is False


class TestHandleTogglePollNotify:
    def test_toggles_flag_and_shows_settings(self, handler, user_svc):
        user_svc.get_or_create(tg_id=9310, username="u", first_name="X")
        result = handler.handle_toggle_poll_notify(tg_id=9310)
        assert SETTINGS_MENU in result.text
        assert user_svc.get_by_tg_id(9310).notify_poll is True

    def test_keyboard_reflects_state(self, handler, user_svc):
        user_svc.get_or_create(tg_id=9311, username="u", first_name="X")
        handler.handle_toggle_poll_notify(tg_id=9311)
        result = handler.handle_settings(tg_id=9311)
        buttons_text = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert any("Уведомления о голосованиях: вкл" in t for t in buttons_text)


# --- UserService: роль организатора голосований ---


class TestPollOrganizerRole:
    def test_default_is_false(self, user_svc):
        user_svc.get_or_create(tg_id=9400, username="u", first_name="X")
        assert user_svc.is_poll_organizer(9400) is False

    def test_toggle_grants_and_revokes(self, user_svc):
        user_svc.get_or_create(tg_id=9401, username="u", first_name="X")
        assert user_svc.toggle_poll_organizer(9401) is True
        assert user_svc.is_poll_organizer(9401) is True
        assert user_svc.toggle_poll_organizer(9401) is False
        assert user_svc.is_poll_organizer(9401) is False

    def test_toggle_unknown_user_returns_none(self, user_svc):
        assert user_svc.toggle_poll_organizer(99999) is None
        assert user_svc.is_poll_organizer(99999) is False
