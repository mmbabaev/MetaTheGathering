"""Tests for admin handler business logic (AdminHandler methods)."""

import pytest
from core.schemas import TournamentCreate
from core.models import TournamentStatus
from bot.handlers.admin import (
    AdminHandler,
    parse_add_player_command,
    parse_bulk_player_line,
    _player_display_label,
)
from bot.messages import (
    NOT_ADMIN,
    NO_DECK_NAME,
    NO_ACTIVE_TOURNAMENT,
    MULTIPLE_TOURNAMENTS_MSG,
    PLAYER_ADDED,
    TOURNAMENT_CLOSED_MSG,
)

ADMIN_TG_ID = 9999
CHAT_ID = 100


class TestParseAddPlayerCommand:
    """Поведение как у Telegram: /add_player@X может означать бота X или игрока X."""

    def test_standard_form(self):
        assert parse_add_player_command("/add_player @testuser Elves", "metabot") == (
            "testuser",
            "Elves",
        )

    def test_player_mistaken_for_command_suffix(self):
        """Частая ошибка: /add_player@testuser Elves — testuser это игрок, не бот."""
        assert parse_add_player_command("/add_player@testuser Elves", "metabot") == (
            "testuser",
            "Elves",
        )

    def test_with_real_bot_suffix(self):
        assert parse_add_player_command(
            "/add_player@metabot @alice Burn", "metabot"
        ) == ("alice", "Burn")

    def test_bot_suffix_case_insensitive(self):
        assert parse_add_player_command(
            "/add_player@MetaBot @alice Burn", "metabot"
        ) == ("alice", "Burn")

    def test_multiword_deck(self):
        assert parse_add_player_command(
            "/add_player @bob Izzet Faeries", "bot"
        ) == ("bob", "Izzet Faeries")

    def test_mistaken_suffix_multiword_deck(self):
        assert parse_add_player_command(
            "/add_player@bob Izzet Faeries", "metabot"
        ) == ("bob", "Izzet Faeries")

    def test_narrow_no_break_space_between_username_and_deck(self):
        """Клиенты Telegram иногда ставят U+202F между @user и колодой — как пробел, но split() его не режет."""
        assert parse_add_player_command(
            "/add_player @testuser\u202fElves", "metabot"
        ) == ("testuser", "Elves")

    def test_missing_deck_returns_none(self):
        assert parse_add_player_command("/add_player @alice", "bot") is None

    def test_missing_everything_returns_none(self):
        assert parse_add_player_command("/add_player", "bot") is None

    def test_wrong_suffix_no_deck_returns_none(self):
        assert parse_add_player_command("/add_player@testuser", "metabot") is None


class TestParseBulkPlayerLine:
    def test_ok(self):
        assert parse_bulk_player_line("@alice Burn") == ("alice", "Burn")

    def test_multiword_deck(self):
        assert parse_bulk_player_line("@bob Izzet Faeries") == ("bob", "Izzet Faeries")

    def test_no_deck(self):
        assert parse_bulk_player_line("@bob") is None


@pytest.fixture
def admin_user(user_svc, svc):
    u = user_svc.get_or_create(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin")
    from core import models
    from sqlalchemy import select
    stmt = select(models.User).where(models.User.tg_id == ADMIN_TG_ID)
    obj = svc.db.execute(stmt).scalar_one()
    obj.is_admin = True
    svc.db.commit()
    return u


@pytest.fixture
def active_tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Weekly", chat_id=CHAT_ID, slug="weekly"))


@pytest.fixture
def handler(svc, user_svc):
    return AdminHandler(svc, user_svc)


# --- handle_add_me ---

class TestHandleAddMe:
    def test_non_admin_returns_not_admin(self, handler):
        result = handler.handle_add_me(tg_id=42, username="x", first_name="X", last_name=None, deck_name="Burn")
        assert result.text == NOT_ADMIN

    def test_empty_deck_name_returns_usage(self, handler, admin_user):
        result = handler.handle_add_me(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin", last_name=None, deck_name="")
        assert result.text == NO_DECK_NAME

    def test_no_active_tournament(self, handler, admin_user):
        result = handler.handle_add_me(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin", last_name=None, deck_name="Burn")
        assert result.text == NO_ACTIVE_TOURNAMENT

    def test_registers_successfully(self, handler, admin_user, active_tournament):
        result = handler.handle_add_me(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin", last_name=None, deck_name="Burn")
        assert "admin" in result.text
        assert "Burn" in result.text

    def test_already_registered(self, handler, admin_user, active_tournament):
        handler.handle_add_me(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin", last_name=None, deck_name="Burn")
        result = handler.handle_add_me(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin", last_name=None, deck_name="Burn")
        assert "уже записаны" in result.text

    def test_multiple_tournaments_returns_clarification(self, handler, svc, admin_user, active_tournament):
        svc.create_tournament(TournamentCreate(title="Second", chat_id=CHAT_ID + 1))
        result = handler.handle_add_me(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin", last_name=None, deck_name="Burn")
        assert result.text == MULTIPLE_TOURNAMENTS_MSG


# --- handle_add_player ---

class TestHandleAddPlayer:
    def test_non_admin_returns_not_admin(self, handler, user_alice):
        result = handler.handle_add_player(
            tg_id=42,
            target_tg_id=user_alice.tg_id,
            target_username="alice",
            deck_name="Burn",
        )
        assert result.text == NOT_ADMIN

    def test_no_active_tournament(self, handler, admin_user, user_alice):
        result = handler.handle_add_player(
            tg_id=ADMIN_TG_ID,
            target_tg_id=user_alice.tg_id,
            target_username="alice",
            deck_name="Burn",
        )
        assert result.text == NO_ACTIVE_TOURNAMENT

    def test_creates_user_by_tg_id_without_prior_row(self, handler, admin_user, active_tournament):
        """Раньше требовали строку в БД после /start; теперь достаточно tg_id (как из getChat)."""
        result = handler.handle_add_player(
            tg_id=ADMIN_TG_ID,
            target_tg_id=77_777,
            target_username="ghost",
            deck_name="Burn",
            target_first_name="Ghost",
        )
        assert "ghost" in result.text or "Ghost" in result.text
        assert "Burn" in result.text

    def test_registers_player_successfully(self, handler, admin_user, active_tournament, user_alice):
        result = handler.handle_add_player(
            tg_id=ADMIN_TG_ID,
            target_tg_id=user_alice.tg_id,
            target_username="alice",
            deck_name="Affinity",
            target_first_name="Alice",
        )
        assert "alice" in result.text
        assert "Affinity" in result.text

    def test_already_registered(self, handler, admin_user, active_tournament, user_alice):
        handler.handle_add_player(
            tg_id=ADMIN_TG_ID,
            target_tg_id=user_alice.tg_id,
            target_username="alice",
            deck_name="Burn",
            target_first_name="Alice",
        )
        result = handler.handle_add_player(
            tg_id=ADMIN_TG_ID,
            target_tg_id=user_alice.tg_id,
            target_username="alice",
            deck_name="Burn",
            target_first_name="Alice",
        )
        assert "уже записан" in result.text

    def test_multiple_tournaments_returns_clarification(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.create_tournament(TournamentCreate(title="Second", chat_id=CHAT_ID + 1))
        result = handler.handle_add_player(
            tg_id=ADMIN_TG_ID,
            target_tg_id=user_alice.tg_id,
            target_username="alice",
            deck_name="Burn",
        )
        assert result.text == MULTIPLE_TOURNAMENTS_MSG


# --- handle_add_players ---

class TestHandleAddPlayers:
    """entries: (target_tg_id, username, first_name, deck_name) — как после getChat в cmd."""

    def test_non_admin_returns_not_admin(self, handler, user_alice):
        result = handler.handle_add_players(
            tg_id=42,
            entries=[(user_alice.tg_id, "alice", "Alice", "Burn")],
        )
        assert result.text == NOT_ADMIN

    def test_empty_entries_returns_no_data(self, handler, admin_user):
        result = handler.handle_add_players(tg_id=ADMIN_TG_ID, entries=[])
        assert result.text == "Нет данных для обработки."

    def test_no_active_tournament(self, handler, admin_user, user_alice):
        result = handler.handle_add_players(
            tg_id=ADMIN_TG_ID,
            entries=[(user_alice.tg_id, "alice", "Alice", "Burn")],
        )
        assert result.text == NO_ACTIVE_TOURNAMENT

    def test_mixed_success_and_duplicate_line(self, handler, admin_user, active_tournament, user_alice):
        entries = [
            (user_alice.tg_id, "alice", "Alice", "Burn"),
            (88_888, "ghost", "Ghost", "Affinity"),
            (user_alice.tg_id, "alice", "Alice", "Burn"),
        ]
        result = handler.handle_add_players(tg_id=ADMIN_TG_ID, entries=entries)
        assert "✅ @alice" in result.text
        assert "✅ @ghost" in result.text
        assert "⚠️ @alice" in result.text
        assert "уже записан" in result.text

    def test_already_registered_line(self, handler, admin_user, active_tournament, user_alice):
        handler.handle_add_player(
            tg_id=ADMIN_TG_ID,
            target_tg_id=user_alice.tg_id,
            target_username="alice",
            deck_name="Burn",
            target_first_name="Alice",
        )
        result = handler.handle_add_players(
            tg_id=ADMIN_TG_ID,
            entries=[(user_alice.tg_id, "alice", "Alice", "Burn")],
        )
        assert "уже записан" in result.text

    def test_multiple_tournaments_returns_clarification(
        self, handler, svc, admin_user, active_tournament, user_alice
    ):
        svc.create_tournament(TournamentCreate(title="Second", chat_id=CHAT_ID + 1))
        result = handler.handle_add_players(
            tg_id=ADMIN_TG_ID,
            entries=[(user_alice.tg_id, "alice", "Alice", "Burn")],
        )
        assert result.text == MULTIPLE_TOURNAMENTS_MSG


# --- handle_tournament_status ---

class TestHandleTournamentStatus:
    def test_non_admin_returns_not_admin(self, handler):
        result = handler.handle_tournament_status(tg_id=42)
        assert result.text == NOT_ADMIN

    def test_no_active_tournament(self, handler, admin_user):
        result = handler.handle_tournament_status(tg_id=ADMIN_TG_ID)
        assert result.text == NO_ACTIVE_TOURNAMENT

    def test_shows_tournament_info(self, handler, admin_user, active_tournament):
        result = handler.handle_tournament_status(tg_id=ADMIN_TG_ID)
        assert "Weekly" in result.text
        assert "Участники" in result.text

    def test_shows_participants_with_archetype(self, handler, svc, admin_user, active_tournament, user_alice, archetype_burn):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        result = handler.handle_tournament_status(tg_id=ADMIN_TG_ID)
        assert "alice" in result.text
        assert "Burn" in result.text

    def test_confirmed_participant_has_checkmark(self, db, handler, svc, admin_user, active_tournament, user_alice, archetype_burn):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        from core import models as m
        from sqlalchemy import select
        p = db.execute(select(m.Participant).where(m.Participant.user_id == user_alice.id)).scalar_one()
        p.confirmed = True
        db.commit()
        result = handler.handle_tournament_status(tg_id=ADMIN_TG_ID)
        assert "✅" in result.text

    def test_shows_all_active_tournaments(self, handler, svc, admin_user, active_tournament):
        from core.schemas import TournamentCreate
        svc.create_tournament(TournamentCreate(title="Second Cup", chat_id=CHAT_ID + 1))
        result = handler.handle_tournament_status(tg_id=ADMIN_TG_ID)
        assert "Weekly" in result.text
        assert "Second Cup" in result.text


# --- handle_close_tournament ---

class TestHandleCloseTournament:
    def test_non_admin_returns_not_admin(self, handler):
        result = handler.handle_close_tournament(tg_id=42)
        assert result.text == NOT_ADMIN

    def test_no_active_tournament(self, handler, admin_user):
        result = handler.handle_close_tournament(tg_id=ADMIN_TG_ID)
        assert result.text == NO_ACTIVE_TOURNAMENT

    def test_closes_tournament(self, handler, svc, admin_user, active_tournament):
        result = handler.handle_close_tournament(tg_id=ADMIN_TG_ID)
        assert result.text == TOURNAMENT_CLOSED_MSG
        assert svc.list_all_active_tournaments() == []

    def test_multiple_tournaments_returns_clarification(self, handler, svc, admin_user, active_tournament):
        svc.create_tournament(TournamentCreate(title="Second", chat_id=CHAT_ID + 1))
        result = handler.handle_close_tournament(tg_id=ADMIN_TG_ID)
        assert result.text == MULTIPLE_TOURNAMENTS_MSG


# --- _is_admin via settings.admin_ids ---

class TestIsAdminViaSettings:
    def test_admin_via_settings_ids(self, handler):
        from unittest.mock import patch
        with patch("bot.handlers.admin.settings") as mock_settings:
            mock_settings.admin_ids = [555]
            assert handler._is_admin(tg_id=555) is True

    def test_non_admin_not_in_settings_or_db(self, handler):
        from unittest.mock import patch
        with patch("bot.handlers.admin.settings") as mock_settings:
            mock_settings.admin_ids = []
            assert handler._is_admin(tg_id=42) is False

    def test_admin_via_db_is_admin_flag(self, handler, admin_user):
        from unittest.mock import patch
        with patch("bot.handlers.admin.settings") as mock_settings:
            mock_settings.admin_ids = []
            assert handler._is_admin(tg_id=ADMIN_TG_ID) is True


# --- handle_add_me: TournamentInvalidState ---

class TestHandleAddMeInvalidState:
    def test_registration_closed_returns_message(self, db, handler, svc, admin_user, active_tournament):
        svc.close_tournament(active_tournament.id)
        # Reopen as ONGOING so it's active but not in REGISTRATION
        from core import models as m
        from sqlalchemy import select
        obj = db.execute(select(m.Tournament).where(m.Tournament.id == active_tournament.id)).scalar_one()
        obj.status = m.TournamentStatus.ONGOING
        db.commit()
        result = handler.handle_add_me(
            tg_id=ADMIN_TG_ID, username="admin", first_name="Admin", last_name=None, deck_name="Burn"
        )
        assert "закрыта" in result.text


# --- handle_add_player: TournamentInvalidState ---

class TestHandleAddPlayerInvalidState:
    def test_registration_closed_returns_message(self, db, handler, svc, admin_user, active_tournament, user_alice):
        from core import models as m
        from sqlalchemy import select
        obj = db.execute(select(m.Tournament).where(m.Tournament.id == active_tournament.id)).scalar_one()
        obj.status = m.TournamentStatus.ONGOING
        db.commit()
        result = handler.handle_add_player(
            tg_id=ADMIN_TG_ID,
            target_tg_id=user_alice.tg_id,
            target_username="alice",
            deck_name="Burn",
        )
        assert "закрыта" in result.text


# --- handle_add_players: TournamentInvalidState ---

class TestHandleAddPlayersInvalidState:
    def test_registration_closed_marks_line(self, db, handler, svc, admin_user, active_tournament, user_alice):
        from core import models as m
        from sqlalchemy import select
        obj = db.execute(select(m.Tournament).where(m.Tournament.id == active_tournament.id)).scalar_one()
        obj.status = m.TournamentStatus.ONGOING
        db.commit()
        result = handler.handle_add_players(
            tg_id=ADMIN_TG_ID,
            entries=[(user_alice.tg_id, "alice", "Alice", "Burn")],
        )
        assert "закрыта" in result.text


# --- parse_add_player_command: uncovered branches ---

class TestParseAddPlayerCommandEdgeCases:
    def test_empty_message_returns_none(self):
        assert parse_add_player_command("", "bot") is None

    def test_whitespace_only_returns_none(self):
        assert parse_add_player_command("   ", "bot") is None

    def test_non_add_player_command_returns_none(self):
        assert parse_add_player_command("/start something", "bot") is None

    def test_empty_username_after_at_returns_none(self):
        # "@ Burn" → username stripped to "" → should return None
        assert parse_add_player_command("/add_player @ Burn", "bot") is None


class TestParseBulkPlayerLineEdgeCases:
    def test_empty_string_returns_none(self):
        assert parse_bulk_player_line("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_bulk_player_line("   ") is None


# --- _player_display_label: no-username branches ---

class TestPlayerDisplayLabel:
    def test_username_present(self):
        assert _player_display_label("alice", "Alice", 1) == "@alice"

    def test_no_username_uses_first_name(self):
        assert _player_display_label(None, "Alice", 1) == "Alice"

    def test_no_username_no_first_name_uses_id(self):
        assert _player_display_label(None, None, 42) == "игрок 42"


# --- handle_add_player: _player_display_label no-username path in result ---

class TestHandleAddPlayerNoUsername:
    def test_already_registered_no_username_shows_first_name(self, handler, svc, user_svc, admin_user, active_tournament):
        target = user_svc.get_or_create(tg_id=5001, username=None, first_name="Bob")
        handler.handle_add_player(
            tg_id=ADMIN_TG_ID,
            target_tg_id=target.tg_id, target_username=None,
            deck_name="Burn", target_first_name="Bob",
        )
        result = handler.handle_add_player(
            tg_id=ADMIN_TG_ID,
            target_tg_id=target.tg_id, target_username=None,
            deck_name="Burn", target_first_name="Bob",
        )
        assert "Bob" in result.text
        assert "уже записан" in result.text

    def test_registered_with_no_username_no_first_name(self, handler, svc, admin_user, active_tournament):
        result = handler.handle_add_player(
            tg_id=ADMIN_TG_ID,
            target_tg_id=6001, target_username=None,
            deck_name="Burn", target_first_name=None,
        )
        assert "6001" in result.text or "Burn" in result.text


# --- handle_tournament_status: full name display ---

class TestTournamentStatusFullName:
    def test_shows_first_and_last_name(self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=6100, username=None, first_name="Иван", last_name="Иванов")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_tournament_status(tg_id=ADMIN_TG_ID)
        assert "Иван" in result.text
        assert "Иванов" in result.text

    def test_shows_username_hint_when_available(self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=6101, username="ivan", first_name="Иван", last_name=None)
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_tournament_status(tg_id=ADMIN_TG_ID)
        assert "Иван" in result.text
        assert "@ivan" in result.text

    def test_falls_back_to_id_when_no_name(self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=6102, username=None, first_name=None)
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_tournament_status(tg_id=ADMIN_TG_ID)
        assert "6102" in result.text
