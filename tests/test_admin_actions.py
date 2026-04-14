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


# --- handle_bulk_add_by_name ---

class TestHandleBulkAddByName:
    def test_non_admin_returns_not_admin(self, handler, active_tournament):
        result = handler.handle_bulk_add_by_name(
            tg_id=42, tournament_id=active_tournament.id, names=["Иван Иванов"]
        )
        assert result.text == NOT_ADMIN

    def test_empty_names_returns_empty_message(self, handler, admin_user, active_tournament):
        from bot.messages import BULK_ADD_EMPTY
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=[]
        )
        assert result.text == BULK_ADD_EMPTY

    def test_blank_lines_only_returns_empty(self, handler, admin_user, active_tournament):
        from bot.messages import BULK_ADD_EMPTY
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["  ", ""]
        )
        assert result.text == BULK_ADD_EMPTY

    def test_creates_new_user_and_adds(self, handler, admin_user, active_tournament, user_svc):
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Иван Иванов"]
        )
        assert "✅ Иван Иванов" in result.text
        user = user_svc.get_or_create_by_name("Иван", "Иванов")
        assert user is not None

    def test_finds_existing_user_by_name(self, handler, admin_user, active_tournament, user_svc):
        user_svc.get_or_create_by_name("Мария", "Петрова")
        user_svc.db.commit()
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Мария Петрова"]
        )
        assert "✅ Мария Петрова" in result.text

    def test_skips_already_registered(self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=7001, username=None, first_name="Алекс")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Алекс"]
        )
        assert "⚠️ Алекс — уже записан" in result.text

    def test_multiple_names_mixed_result(self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn):
        existing = user_svc.get_or_create(tg_id=7002, username=None, first_name="Борис")
        svc.register_participant(tournament_id=active_tournament.id, user_id=existing.id, archetype_id=archetype_burn.id)
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id,
            names=["Борис", "Вера Новая"],
        )
        assert "⚠️ Борис — уже записан" in result.text
        assert "✅ Вера Новая" in result.text

    def test_tournament_not_found(self, handler, admin_user):
        from bot.messages import TOURNAMENT_NOT_FOUND
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=99999, names=["Иван"]
        )
        assert result.text == TOURNAMENT_NOT_FOUND

    def test_registration_closed(self, handler, svc, admin_user, active_tournament):
        from bot.messages import REGISTRATION_CLOSED
        svc.close_tournament(active_tournament.id)
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Иван"]
        )
        assert result.text == REGISTRATION_CLOSED

    def test_first_name_only(self, handler, admin_user, active_tournament):
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Мария"]
        )
        assert "✅ Мария" in result.text


# --- handle_admin_status ---

class TestHandleAdminStatus:
    def test_non_admin_returns_not_admin(self, handler, active_tournament):
        result = handler.handle_admin_status(tg_id=42, tournament_id=active_tournament.id)
        assert result.text == NOT_ADMIN

    def test_returns_text_with_keyboard(self, handler, admin_user, active_tournament):
        result = handler.handle_admin_status(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        assert "Weekly" in result.text
        assert result.keyboard is not None

    def test_tournament_not_found(self, handler, admin_user):
        from bot.messages import TOURNAMENT_NOT_FOUND
        result = handler.handle_admin_status(tg_id=ADMIN_TG_ID, tournament_id=99999)
        assert result.text == TOURNAMENT_NOT_FOUND
        assert result.is_alert

    def test_keyboard_has_button_per_participant(self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=8001, username=None, first_name="Тест")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_admin_status(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        buttons = [b for row in result.keyboard.inline_keyboard for b in row]
        from bot.keyboards import CB_ADMIN_PICK_ARCH
        assert any(b.callback_data.startswith(CB_ADMIN_PICK_ARCH) for b in buttons)

    def test_no_archetype_participant_gets_pencil_prefix(self, handler, svc, user_svc, admin_user, active_tournament):
        user = user_svc.get_or_create(tg_id=8002, username=None, first_name="Безколоды")
        svc.bulk_add_participants(active_tournament.id, [(user.id, "Безколоды")])
        result = handler.handle_admin_status(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        buttons_text = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert any("📝" in t for t in buttons_text)

    def test_with_archetype_participant_gets_edit_prefix(self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=8003, username=None, first_name="Сколодой")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_admin_status(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        buttons_text = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert any("✏️" in t for t in buttons_text)


# --- handle_admin_pick_arch ---

class TestHandleAdminPickArch:
    @pytest.fixture
    def participant(self, svc, user_svc, active_tournament):
        user = user_svc.get_or_create(tg_id=8100, username=None, first_name="Игрок")
        svc.bulk_add_participants(active_tournament.id, [(user.id, "Игрок")])
        return svc.get_participant(active_tournament.id, user.id)

    def test_non_admin_returns_not_admin(self, handler, active_tournament, participant):
        result = handler.handle_admin_pick_arch(tg_id=42, participant_id=participant.id)
        assert result.text == NOT_ADMIN

    def test_returns_archetype_keyboard(self, handler, admin_user, active_tournament, participant, archetype_burn):
        result = handler.handle_admin_pick_arch(tg_id=ADMIN_TG_ID, participant_id=participant.id)
        from bot.messages import CHOOSE_ARCHETYPE
        assert result.text == CHOOSE_ARCHETYPE
        assert result.keyboard is not None

    def test_participant_not_found(self, handler, admin_user):
        from bot.messages import PARTICIPANT_NOT_FOUND
        result = handler.handle_admin_pick_arch(tg_id=ADMIN_TG_ID, participant_id=99999)
        assert result.text == PARTICIPANT_NOT_FOUND
        assert result.is_alert

    def test_keyboard_uses_admin_callbacks(self, handler, admin_user, active_tournament, participant, archetype_burn):
        result = handler.handle_admin_pick_arch(tg_id=ADMIN_TG_ID, participant_id=participant.id)
        from bot.keyboards import CB_ADMIN_SET_ARCH
        buttons = [b for row in result.keyboard.inline_keyboard for b in row]
        assert any(b.callback_data.startswith(CB_ADMIN_SET_ARCH) for b in buttons)


# --- handle_admin_set_arch ---

class TestHandleAdminSetArch:
    @pytest.fixture
    def participant(self, svc, user_svc, active_tournament):
        user = user_svc.get_or_create(tg_id=8200, username=None, first_name="Игрок")
        svc.bulk_add_participants(active_tournament.id, [(user.id, "Игрок")])
        return svc.get_participant(active_tournament.id, user.id)

    def test_non_admin_returns_not_admin(self, handler, active_tournament, participant, archetype_burn):
        result = handler.handle_admin_set_arch(tg_id=42, participant_id=participant.id, archetype_id=archetype_burn.id)
        assert result.text == NOT_ADMIN

    def test_sets_archetype_successfully(self, handler, svc, admin_user, active_tournament, participant, archetype_burn):
        result = handler.handle_admin_set_arch(tg_id=ADMIN_TG_ID, participant_id=participant.id, archetype_id=archetype_burn.id)
        from bot.messages import ADMIN_ARCH_SAVED
        assert "Burn" in result.text
        assert not result.is_alert
        updated = svc.get_participant(active_tournament.id, participant.user_id)
        assert updated.archetype_id == archetype_burn.id

    def test_participant_not_found(self, handler, admin_user, archetype_burn):
        from bot.messages import PARTICIPANT_NOT_FOUND
        result = handler.handle_admin_set_arch(tg_id=ADMIN_TG_ID, participant_id=99999, archetype_id=archetype_burn.id)
        assert result.text == PARTICIPANT_NOT_FOUND
        assert result.is_alert


# --- handle_admin_custom_arch_text ---

class TestHandleAdminCustomArchText:
    @pytest.fixture
    def participant(self, svc, user_svc, active_tournament):
        user = user_svc.get_or_create(tg_id=8300, username=None, first_name="Игрок")
        svc.bulk_add_participants(active_tournament.id, [(user.id, "Игрок")])
        return svc.get_participant(active_tournament.id, user.id)

    def test_non_admin_returns_not_admin(self, handler, participant):
        result = handler.handle_admin_custom_arch_text(tg_id=42, participant_id=participant.id, arch_name="Elves")
        assert result.text == NOT_ADMIN

    def test_creates_archetype_and_sets(self, handler, svc, admin_user, participant):
        result = handler.handle_admin_custom_arch_text(tg_id=ADMIN_TG_ID, participant_id=participant.id, arch_name="Turbo Fog")
        from bot.messages import ADMIN_ARCH_SAVED
        assert "Turbo Fog" in result.text
        assert not result.is_alert

    def test_participant_not_found(self, handler, admin_user):
        from bot.messages import PARTICIPANT_NOT_FOUND
        result = handler.handle_admin_custom_arch_text(tg_id=ADMIN_TG_ID, participant_id=99999, arch_name="Elves")
        assert result.text == PARTICIPANT_NOT_FOUND
        assert result.is_alert


class TestHandleAdminPickArchUsesParticipantHistory:
    """Убеждаемся что список архетипов персонализирован под игрока, а не под админа."""

    @pytest.fixture
    def setup(self, svc, user_svc, active_tournament):
        from core.schemas import TournamentCreate as TC
        burn = svc.get_or_create_archetype_by_name("Burn")
        elves = svc.get_or_create_archetype_by_name("Elves")

        # Прошлый турнир: админ играл Burn
        t_admin = svc.create_tournament(TC(title="Admin Hist", chat_id=CHAT_ID + 50, slug="ah"))
        admin = user_svc.get_or_create(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin")
        svc.register_participant(tournament_id=t_admin.id, user_id=admin.id, archetype_id=burn.id)

        # Прошлый турнир: игрок играл Elves
        player = user_svc.get_or_create(tg_id=8888, username=None, first_name="Player")
        t_player = svc.create_tournament(TC(title="Player Hist", chat_id=CHAT_ID + 51, slug="ph"))
        svc.register_participant(tournament_id=t_player.id, user_id=player.id, archetype_id=elves.id)

        # Активный турнир: игрок добавлен без колоды
        svc.bulk_add_participants(active_tournament.id, [(player.id, "Player")])
        participant = svc.get_participant(active_tournament.id, player.id)
        return participant, burn, elves

    def test_first_archetype_is_player_history_not_admin_history(self, handler, admin_user, active_tournament, setup):
        participant, burn, elves = setup
        result = handler.handle_admin_pick_arch(tg_id=ADMIN_TG_ID, participant_id=participant.id)

        first_btn = result.keyboard.inline_keyboard[0][0]
        # Elves — история игрока, должна стоять первой
        assert "Elves" in first_btn.text, (
            f"Ожидали Elves (история игрока) первым архетипом, но получили: {first_btn.text}"
        )
        # Burn — история админа, не должна быть первой
        assert "Burn" not in first_btn.text

    def test_bulk_added_player_no_history_gets_top_by_popularity_not_admin_order(
        self, handler, svc, user_svc, admin_user, active_tournament
    ):
        """Игрок без истории (bulk add) должен получать топ по глобальной популярности,
        а не персональный список колод админа.

        Сценарий: «Zzz Deck» — колода админа (1 использование), «Aaa Deck» — сыграна
        двумя другими игроками (2 использования). Для игрока без истории топ должен
        показать «Aaa Deck» первой (она глобально популярнее).
        """
        from core.schemas import TournamentCreate as TC

        aaa = svc.get_or_create_archetype_by_name("Aaa Deck")
        zzz = svc.get_or_create_archetype_by_name("Zzz Deck")

        # Прошлый турнир: админ играл Zzz (1 раз)
        t_admin = svc.create_tournament(TC(title="Admin Z hist", chat_id=CHAT_ID + 60, slug="az"))
        admin = user_svc.get_or_create(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin")
        svc.register_participant(tournament_id=t_admin.id, user_id=admin.id, archetype_id=zzz.id)

        # Ещё два других игрока играли Aaa (больше использований у Aaa)
        u1 = user_svc.get_or_create(tg_id=7701, username=None, first_name="Player1")
        u2 = user_svc.get_or_create(tg_id=7702, username=None, first_name="Player2")
        t_other = svc.create_tournament(TC(title="Other hist", chat_id=CHAT_ID + 61, slug="oh"))
        svc.register_participant(tournament_id=t_other.id, user_id=u1.id, archetype_id=aaa.id)
        svc.register_participant(tournament_id=t_other.id, user_id=u2.id, archetype_id=aaa.id)

        # Игрок добавлен через bulk_add — нет истории архетипов
        player = user_svc.get_or_create_by_name("Bulk", "Player")[0]
        svc.bulk_add_participants(active_tournament.id, [(player.id, "Bulk Player")])
        participant = svc.get_participant(active_tournament.id, player.id)

        result = handler.handle_admin_pick_arch(tg_id=ADMIN_TG_ID, participant_id=participant.id)

        all_btn_names = [
            b.text for row in result.keyboard.inline_keyboard for b in row
        ]
        first_btn = result.keyboard.inline_keyboard[0][0]

        assert "Aaa Deck" in first_btn.text, (
            f"Ожидали 'Aaa Deck' первым (глобальный топ: 2 использования у Aaa vs 1 у Zzz), "
            f"но получили: {first_btn.text!r}. Все кнопки: {all_btn_names}"
        )


# ---------------------------------------------------------------------------
# Возврат статуса турнира после действий
# ---------------------------------------------------------------------------

class TestStatusReturnedAfterBulkAdd:
    """После bulk_add ответ содержит статус турнира и клавиатуру участников."""

    def test_result_contains_add_summary(self, handler, admin_user, active_tournament):
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Иван Иванов"]
        )
        assert "✅ Иван Иванов" in result.text

    def test_result_contains_tournament_status(self, handler, admin_user, active_tournament):
        """После добавления текст содержит заголовок турнира."""
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Иван Иванов"]
        )
        assert active_tournament.title in result.text

    def test_result_has_participants_keyboard(self, handler, admin_user, active_tournament):
        """После добавления клавиатура содержит кнопки участников."""
        from bot.keyboards import CB_ADMIN_PICK_ARCH
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Иван Иванов"]
        )
        assert result.keyboard is not None
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(cb.startswith(CB_ADMIN_PICK_ARCH) for cb in cbs)

    def test_add_summary_comes_before_status(self, handler, admin_user, active_tournament):
        """Строки добавления идут перед блоком статуса."""
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Пётр Петров"]
        )
        pos_add = result.text.index("✅ Пётр Петров")
        pos_title = result.text.index(active_tournament.title)
        assert pos_add < pos_title

    def test_multiple_players_all_in_text_and_keyboard(self, handler, admin_user, active_tournament):
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id,
            names=["Анна Первая", "Борис Второй"],
        )
        assert "✅ Анна Первая" in result.text
        assert "✅ Борис Второй" in result.text
        from bot.keyboards import CB_ADMIN_PICK_ARCH
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert sum(1 for cb in cbs if cb.startswith(CB_ADMIN_PICK_ARCH)) == 2


class TestStatusReturnedAfterSetArch:
    """После назначения архетипа ответ содержит статус турнира и клавиатуру участников."""

    @pytest.fixture
    def participant(self, svc, user_svc, active_tournament):
        user = user_svc.get_or_create(tg_id=9200, username=None, first_name="Игрок")
        svc.bulk_add_participants(active_tournament.id, [(user.id, "Игрок")])
        return svc.get_participant(active_tournament.id, user.id)

    @pytest.fixture
    def archetype_burn(self, svc):
        return svc.get_or_create_archetype_by_name("Burn")

    def test_result_contains_arch_name(
        self, handler, admin_user, active_tournament, participant, archetype_burn
    ):
        result = handler.handle_admin_set_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, archetype_id=archetype_burn.id
        )
        assert "Burn" in result.text

    def test_result_contains_tournament_status(
        self, handler, admin_user, active_tournament, participant, archetype_burn
    ):
        result = handler.handle_admin_set_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, archetype_id=archetype_burn.id
        )
        assert active_tournament.title in result.text

    def test_result_has_participants_keyboard(
        self, handler, admin_user, active_tournament, participant, archetype_burn
    ):
        from bot.keyboards import CB_ADMIN_PICK_ARCH
        result = handler.handle_admin_set_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, archetype_id=archetype_burn.id
        )
        assert result.keyboard is not None
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(cb.startswith(CB_ADMIN_PICK_ARCH) for cb in cbs)

    def test_arch_saved_message_comes_before_status(
        self, handler, admin_user, active_tournament, participant, archetype_burn
    ):
        result = handler.handle_admin_set_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, archetype_id=archetype_burn.id
        )
        pos_arch = result.text.index("Burn")
        pos_title = result.text.index(active_tournament.title)
        assert pos_arch < pos_title

    def test_archetype_actually_saved_in_db(
        self, handler, svc, admin_user, active_tournament, participant, archetype_burn
    ):
        handler.handle_admin_set_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, archetype_id=archetype_burn.id
        )
        updated = svc.get_participant(active_tournament.id, participant.user_id)
        assert updated.archetype_id == archetype_burn.id

    def test_keyboard_button_has_edit_prefix_after_arch_set(
        self, handler, admin_user, active_tournament, participant, archetype_burn
    ):
        """После назначения колоды кнопка участника должна иметь prefix ✏️."""
        result = handler.handle_admin_set_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, archetype_id=archetype_burn.id
        )
        btns = [b for row in result.keyboard.inline_keyboard for b in row]
        participant_btn = next(
            (b for b in btns if str(participant.id) in b.callback_data), None
        )
        assert participant_btn is not None
        assert participant_btn.text.startswith("✏️")
