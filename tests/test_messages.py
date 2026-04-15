import bot.messages as msg
from bot.messages import format_tournament_card, format_tournament_status


class _FakeArchetype:
    def __init__(self, name): self.name = name

class _FakeUser:
    def __init__(self, fn, ln=None, uname=None, tg_id=1):
        self.first_name, self.last_name, self.username, self.tg_id = fn, ln, uname, tg_id

class _FakeParticipant:
    def __init__(self, user, archetype=None, confirmed=False):
        self.user, self.archetype, self.confirmed = user, archetype, confirmed


class TestFormatTournamentCard:
    def test_includes_title_and_status(self):
        result = format_tournament_card("Pauper Cup", "Регистрация")
        assert "Pauper Cup" in result
        assert "Регистрация" in result

    def test_includes_participant_count(self):
        result = format_tournament_card("Pauper Cup", "Идёт", total=8, with_deck=5)
        assert "8" in result
        assert "5" in result

    def test_no_count_when_not_provided(self):
        result = format_tournament_card("Pauper Cup", "Идёт")
        assert "чел." not in result

    def test_compact_single_line(self):
        result = format_tournament_card("Pauper Cup", "Регистрация")
        assert "\n" not in result


class TestFormatTournamentStatus:
    def _p(self, name, deck=None, confirmed=False):
        return _FakeParticipant(_FakeUser(name), _FakeArchetype(deck) if deck else None, confirmed)

    def test_header_contains_title_and_status(self):
        result = format_tournament_status("Cup", "Регистрация", [])
        assert "Cup" in result and "Регистрация" in result

    def test_confirmed_shows_checkmark(self):
        p = self._p("Иван", deck="Burn", confirmed=True)
        result = format_tournament_status("Cup", "Reg", [p])
        assert "✅" in result

    def test_deck_without_confirmation_shows_rotation(self):
        p = self._p("Иван", deck="Burn", confirmed=False)
        result = format_tournament_status("Cup", "Reg", [p])
        assert "🔄" in result

    def test_no_deck_shows_empty_box(self):
        p = self._p("Иван")
        result = format_tournament_status("Cup", "Reg", [p])
        assert "⬜" in result

    def test_shows_player_name(self):
        p = self._p("Иванов", "Burn")
        result = format_tournament_status("Cup", "Reg", [p])
        assert "Иванов" in result

    def test_shows_deck_name(self):
        p = self._p("Иван", "Rakdos Madness")
        result = format_tournament_status("Cup", "Reg", [p])
        assert "Rakdos Madness" in result

    def test_summary_line_shows_counts(self):
        participants = [
            self._p("А", "Burn", True),
            self._p("Б", "Elves", False),
            self._p("В"),
        ]
        result = format_tournament_status("Cup", "Reg", participants)
        assert "2" in result  # with deck
        assert "1" in result  # without


class TestMessageTemplates:
    def test_telegram_user_lookup_failed_template(self):
        result = msg.TELEGRAM_USER_LOOKUP_FAILED.format(username="alice")
        assert "@alice" in result

    def test_player_added_template(self):
        result = msg.PLAYER_ADDED.format(user="@alice", archetype_name="Burn")
        assert "@alice" in result
        assert "Burn" in result

    def test_registered_as_template(self):
        result = msg.REGISTERED_AS.format(archetype_name="Affinity")
        assert "Affinity" in result

    def test_all_constants_are_non_empty(self):
        constants = [
            msg.NO_ACTIVE_TOURNAMENTS, msg.CHOOSE_ARCHETYPE, msg.CUSTOM_ARCHETYPE_PROMPT,
            msg.REGISTERED, msg.ALREADY_REGISTERED, msg.REGISTRATION_CLOSED,
            msg.TOURNAMENT_NOT_FOUND, msg.NOT_ADMIN, msg.NO_DECK_NAME,
            msg.NO_ACTIVE_TOURNAMENT, msg.TOURNAMENT_CLOSED_MSG, msg.ADD_PLAYERS_USAGE,
            msg.HELP_TEXT,
        ]
        for constant in constants:
            assert isinstance(constant, str) and len(constant) > 0

    def test_help_text_covers_main_commands(self):
        for cmd in ("/tournaments", "/tournament_status", "/add_me", "/add_player", "/close_tournament"):
            assert cmd in msg.HELP_TEXT
