"""Tests for deck emoji labels (bot/deck_emoji.py)."""

import pytest

from bot.deck_emoji import _DECK_EMOJI, _key, deck_emoji


class TestGet:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Jeskai Ephemerate", "🦁💧🔥"),
            ("Red Kuldotha", "🔴👺"),
        ],
    )
    def test_known_decks(self, name, expected):
        assert deck_emoji.get(name) == expected

    @pytest.mark.parametrize(
        "name",
        [
            "Jeskai Ephemerate",
            "Jeskai ephemerate",  # так тоже пишут в базе
            "jeskai ephemerate",
            "JESKAI EPHEMERATE",
            "  Jeskai Ephemerate  ",
        ],
    )
    def test_case_and_spaces_do_not_matter(self, name):
        """Игроки вводят названия руками — регистр и лишние пробелы не должны мешать."""
        assert deck_emoji.get(name) == "🦁💧🔥"

    def test_unknown_deck_has_no_emoji(self):
        assert deck_emoji.get("Совсем незнакомая колода") == ""


class TestFormat:
    def test_prefixes_known_deck(self):
        assert deck_emoji.format("Jeskai Ephemerate") == "🦁💧🔥 Jeskai Ephemerate"

    def test_keeps_the_name_as_typed(self):
        """В кнопке остаётся то, что ввёл игрок, — нормализация только для поиска."""
        assert deck_emoji.format("jeskai ephemerate") == "🦁💧🔥 jeskai ephemerate"

    def test_unknown_deck_stays_plain(self):
        """Без эмодзи — просто имя, без ведущего пробела."""
        assert deck_emoji.format("Unknown Brew") == "Unknown Brew"


class TestBookIntegrity:
    def test_no_empty_emoji(self):
        """Пустое значение молча превратило бы кнопку в обычное имя."""
        assert [name for name, emoji in _DECK_EMOJI.items() if not emoji.strip()] == []

    def test_no_case_insensitive_collisions(self):
        """Два ключа, различающиеся только регистром, молча схлопнулись бы в индексе —
        и одна из колод потеряла бы свои эмодзи."""
        seen: dict[str, str] = {}
        collisions = []
        for name, emoji in _DECK_EMOJI.items():
            previous = seen.get(_key(name))
            if previous is not None and previous != emoji:
                collisions.append(name)
            seen[_key(name)] = emoji
        assert collisions == []
