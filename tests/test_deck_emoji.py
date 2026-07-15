"""Tests for deck emoji labels (bot/deck_emoji.py)."""

import pytest

from bot.deck_emoji import _DECK_EMOJI, deck_emoji


class TestGet:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Jeskai Ephemerate", "🦁💧🔥"),
            ("Jeskai ephemerate", "🦁💧🔥"),  # в базе живут оба написания
            ("Red Kuldotha", "🔴👺"),
        ],
    )
    def test_known_decks(self, name, expected):
        assert deck_emoji.get(name) == expected

    def test_unknown_deck_has_no_emoji(self):
        assert deck_emoji.get("Совсем незнакомая колода") == ""


class TestFormat:
    def test_prefixes_known_deck(self):
        assert deck_emoji.format("Jeskai Ephemerate") == "🦁💧🔥 Jeskai Ephemerate"

    def test_unknown_deck_stays_plain(self):
        """Без эмодзи — просто имя, без ведущего пробела."""
        assert deck_emoji.format("Unknown Brew") == "Unknown Brew"


class TestBookIntegrity:
    def test_no_empty_emoji(self):
        """Пустое значение молча превратило бы кнопку в обычное имя."""
        assert [name for name, emoji in _DECK_EMOJI.items() if not emoji.strip()] == []

    def test_names_are_not_padded(self):
        """Ключ — точное название из базы: лишний пробел = промах по словарю."""
        assert [name for name in _DECK_EMOJI if name != name.strip()] == []
