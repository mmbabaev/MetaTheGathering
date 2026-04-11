import bot.messages as msg
from bot.messages import format_tournament_card


class TestFormatTournamentCard:
    def test_includes_title_and_status(self):
        result = format_tournament_card("Pauper Cup", "Регистрация")
        assert "Pauper Cup" in result
        assert "Регистрация" in result

    def test_includes_slug_when_provided(self):
        result = format_tournament_card("Pauper Cup", "Идёт", slug="2026-03-28-pauper")
        assert "2026-03-28-pauper" in result

    def test_no_slug_when_none(self):
        result = format_tournament_card("Pauper Cup", "Идёт", slug=None)
        assert "Slug" not in result

    def test_empty_slug_not_shown(self):
        result = format_tournament_card("Pauper Cup", "Идёт", slug="")
        assert "Slug" not in result


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
