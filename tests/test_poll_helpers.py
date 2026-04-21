"""Tests for pure helper functions in bot/telegram/poll.py."""

from bot.telegram.poll import _poll_message_link


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
