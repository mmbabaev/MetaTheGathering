"""Tests for pure helper functions in bot/telegram/poll.py."""

from types import SimpleNamespace

from bot.keyboards import (
    CB_CREATE_POLL,
    CB_LINK_POLL_BY_URL,
    CB_NOTIFY_NO_DECK,
    CB_POLL_CLUB,
    CB_POLL_ORG_MENU,
    CB_POLL_PING,
    CB_POLL_REGULAR_TOGGLE,
    CB_POLL_REGULARS,
    poll_club_menu_keyboard,
    poll_clubs_keyboard,
    poll_menu_keyboard,
    poll_regulars_keyboard,
)
from bot.telegram.poll import _display_name, _parse_message_link, _poll_message_link


class TestPollMessageLink:
    def test_public_group_uses_username(self):
        link = _poll_message_link(-5194706758, 42, chat_username="testgroup")
        assert link == "https://t.me/testgroup/42"

    def test_supergroup_without_username(self):
        link = _poll_message_link(-1001234567890, 99)
        assert link == "https://t.me/c/1234567890/99"

    def test_basic_group_returns_none(self):
        assert _poll_message_link(-5194706758, 42) is None

    def test_positive_chat_id_returns_none(self):
        assert _poll_message_link(12345, 1) is None

    def test_username_takes_priority_over_supergroup_format(self):
        link = _poll_message_link(-1001234567890, 5, chat_username="mygroup")
        assert link == "https://t.me/mygroup/5"


class TestPollMenuKeyboard:
    def _flat_buttons(self, keyboard):
        return [btn for row in keyboard.inline_keyboard for btn in row]

    def test_without_poll_link_has_four_buttons(self):
        kb = poll_menu_keyboard(1)
        buttons = self._flat_buttons(kb)
        assert len(buttons) == 4
        texts = [b.text for b in buttons]
        assert any("Создать" in t for t in texts)
        assert any("Привязать" in t for t in texts)
        assert any("Напомнить" in t for t in texts)
        assert any("Назад" in t for t in texts)
        assert not any(b.url for b in buttons)

    def test_with_poll_link_has_four_buttons(self):
        kb = poll_menu_keyboard(1, poll_link="https://t.me/testgroup/42")
        buttons = self._flat_buttons(kb)
        assert len(buttons) == 4
        url_buttons = [b for b in buttons if b.url]
        assert len(url_buttons) == 1
        assert url_buttons[0].url == "https://t.me/testgroup/42"

    def test_create_and_notify_use_correct_callbacks(self):
        kb = poll_menu_keyboard(7)
        buttons = self._flat_buttons(kb)
        cb_data = [b.callback_data for b in buttons if b.callback_data]
        assert f"{CB_CREATE_POLL}:7" in cb_data
        assert f"{CB_NOTIFY_NO_DECK}:7" in cb_data

    def test_link_by_url_button_shown_when_no_poll(self):
        kb = poll_menu_keyboard(5)
        buttons = self._flat_buttons(kb)
        cb_data = [b.callback_data for b in buttons if b.callback_data]
        assert f"{CB_LINK_POLL_BY_URL}:5" in cb_data

    def test_link_by_url_button_absent_when_poll_linked(self):
        kb = poll_menu_keyboard(5, poll_link="https://t.me/g/1")
        buttons = self._flat_buttons(kb)
        cb_data = [b.callback_data for b in buttons if b.callback_data]
        assert not any(CB_LINK_POLL_BY_URL in (d or "") for d in cb_data)


class TestParseMessageLink:
    def test_supergroup_link(self):
        chat_id, msg_id = _parse_message_link("https://t.me/c/1003631429183/42")
        assert chat_id == -1001003631429183
        assert msg_id == 42

    def test_public_group_link(self):
        chat_id, msg_id = _parse_message_link("https://t.me/metathegatheringtestgroup/99")
        assert chat_id == "@metathegatheringtestgroup"
        assert msg_id == 99

    def test_invalid_link_returns_none(self):
        assert _parse_message_link("not a link") is None
        assert _parse_message_link("https://example.com/foo") is None

    def test_strips_whitespace(self):
        result = _parse_message_link("  https://t.me/c/1234567890/5  ")
        assert result is not None


class TestDisplayName:
    def test_username_and_name(self):
        u = SimpleNamespace(username="alice", first_name="Alice", last_name="Cooper", tg_id=1)
        assert _display_name(u) == "@alice Alice Cooper"

    def test_only_name(self):
        u = SimpleNamespace(username=None, first_name="Боб", last_name=None, tg_id=2)
        assert _display_name(u) == "Боб"

    def test_fallback_to_id(self):
        u = SimpleNamespace(username=None, first_name=None, last_name=None, tg_id=42)
        assert _display_name(u) == "id42"


class TestPollOrganizerKeyboards:
    def _flat(self, kb):
        return [b for row in kb.inline_keyboard for b in row]

    def test_clubs_keyboard_one_button_per_club(self):
        kb = poll_clubs_keyboard([(100, "Goldfish"), (-1001, "Единорог")])
        buttons = self._flat(kb)
        assert [b.text for b in buttons] == ["Goldfish", "Единорог"]
        assert buttons[1].callback_data == f"{CB_POLL_CLUB}:-1001"

    def test_club_menu_shows_count_and_back(self):
        kb = poll_club_menu_keyboard(100, regulars_count=3)
        buttons = self._flat(kb)
        assert any("Регуляры (3)" in b.text for b in buttons)
        assert any(b.callback_data == f"{CB_POLL_PING}:100" for b in buttons)
        assert any(b.callback_data == CB_POLL_ORG_MENU for b in buttons)

    def test_regulars_keyboard_marks_and_pagination(self):
        players = [(i, f"p{i}") for i in range(10)]
        regular_ids = {0, 3}
        kb = poll_regulars_keyboard(100, players, regular_ids, page=0, page_size=8)
        buttons = self._flat(kb)
        # 8 игроков на странице
        marked = [b for b in buttons if b.text.startswith("✅") or b.text.startswith("⬜️")]
        assert len(marked) == 8
        assert marked[0].text.startswith("✅")  # user 0 — регуляр
        assert marked[1].text.startswith("⬜️")  # user 1 — нет
        assert marked[0].callback_data == f"{CB_POLL_REGULAR_TOGGLE}:100:0:0"
        # есть кнопка «вперёд» (10 > 8), нет «назад» на первой странице
        nav = [b for b in buttons if b.callback_data and b.callback_data.startswith(f"{CB_POLL_REGULARS}:")]
        assert any("▶️" in b.text for b in nav)
        assert not any("◀️" in b.text for b in nav)

    def test_regulars_keyboard_second_page_has_back_nav(self):
        players = [(i, f"p{i}") for i in range(10)]
        kb = poll_regulars_keyboard(100, players, set(), page=1, page_size=8)
        buttons = self._flat(kb)
        marked = [b for b in buttons if b.text.startswith("✅") or b.text.startswith("⬜️")]
        assert len(marked) == 2  # осталось 2 игрока
        nav = [b for b in buttons if b.callback_data and b.callback_data.startswith(f"{CB_POLL_REGULARS}:")]
        assert any("◀️" in b.text for b in nav)
        assert not any("▶️" in b.text for b in nav)
