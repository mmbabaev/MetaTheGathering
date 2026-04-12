"""Tests for player handler business logic (handle_xxx functions)."""

import pytest
from core.schemas import TournamentCreate
from core.models import TournamentStatus, utc_now
from bot.handlers.player import (
    handle_tournaments,
    handle_tournament_select,
    handle_register,
    handle_archetype,
    handle_custom_archetype_text,
)
from bot.messages import (
    NO_ACTIVE_TOURNAMENTS,
    CHOOSE_ARCHETYPE,
    REGISTERED_AS,
    REGISTERED,
    ALREADY_REGISTERED,
    REGISTRATION_CLOSED,
    TOURNAMENT_NOT_FOUND,
)

CHAT_ID = 200


@pytest.fixture
def active_tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Open", chat_id=CHAT_ID, slug="open"))


# --- handle_tournaments ---

class TestHandleTournaments:
    def test_no_tournaments_returns_message(self, db):
        result = handle_tournaments(db)
        assert result.text == NO_ACTIVE_TOURNAMENTS
        assert result.keyboard is None

    def test_single_tournament_returns_card_with_register_button(self, db, active_tournament):
        result = handle_tournaments(db)
        assert "Open" in result.text
        assert result.keyboard is not None

    def test_multiple_tournaments_returns_list(self, db):
        from core import models
        # Insert two tournaments in different chats
        for i, slug in enumerate(("t1", "t2"), start=1):
            db.add(models.Tournament(
                title=slug.upper(), chat_id=CHAT_ID + i, slug=slug,
                status=models.TournamentStatus.REGISTRATION,
                created_at=utc_now(),
            ))
        db.commit()
        result = handle_tournaments(db)
        assert "Выберите турнир" in result.text
        assert result.keyboard is not None

    def test_closed_tournament_not_shown(self, db, svc, active_tournament):
        svc.close_tournament(active_tournament.id)
        result = handle_tournaments(db)
        assert result.text == NO_ACTIVE_TOURNAMENTS

    def test_shows_tournaments_from_all_chats(self, db, svc, active_tournament):
        """Турниры из разных чатов видны в общем списке."""
        svc.create_tournament(TournamentCreate(title="Other Chat", chat_id=CHAT_ID + 1, slug="other"))
        result = handle_tournaments(db)
        assert "Выберите турнир" in result.text


# --- handle_tournament_select ---

class TestHandleTournamentSelect:
    def test_valid_tournament_returns_card(self, db, active_tournament):
        result = handle_tournament_select(db, active_tournament.id)
        assert "Open" in result.text
        assert result.keyboard is not None
        assert not result.is_alert

    def test_not_found_returns_alert(self, db):
        result = handle_tournament_select(db, tournament_id=99999)
        assert result.text == TOURNAMENT_NOT_FOUND
        assert result.is_alert


# --- handle_register ---

class TestHandleRegister:
    def test_returns_archetype_choice_no_tg_id(self, db, active_tournament, archetype_burn, archetype_affinity):
        result = handle_register(db, active_tournament.id)
        assert result.text == CHOOSE_ARCHETYPE
        assert result.keyboard is not None
        assert not result.needs_name

    def test_returns_archetype_choice_when_user_has_name(self, db, svc, active_tournament, archetype_burn):
        user = svc.get_or_create_user(tg_id=5100, username="u", first_name="Иван")
        result = handle_register(db, active_tournament.id, tg_id=user.tg_id)
        assert result.text == CHOOSE_ARCHETYPE
        assert result.keyboard is not None
        assert not result.needs_name

    def test_needs_name_when_user_has_no_name(self, db, svc, active_tournament):
        user = svc.get_or_create_user(tg_id=5101, username="u", first_name=None)
        result = handle_register(db, active_tournament.id, tg_id=user.tg_id)
        assert result.needs_name is True
        assert result.keyboard is None

    def test_needs_name_when_user_unknown(self, db, active_tournament):
        result = handle_register(db, active_tournament.id, tg_id=99999)
        assert result.needs_name is True


# --- handle_archetype ---

class TestHandleArchetype:
    def test_registers_successfully(self, db, active_tournament, archetype_burn):
        result = handle_archetype(
            db, tg_id=1001, username="alice", first_name="Alice", last_name=None,
            tournament_id=active_tournament.id, archetype_id=archetype_burn.id,
        )
        assert "Burn" in result.text
        assert not result.is_alert

    def test_already_registered_returns_alert(self, db, active_tournament, archetype_burn):
        handle_archetype(
            db, tg_id=1001, username="alice", first_name="Alice", last_name=None,
            tournament_id=active_tournament.id, archetype_id=archetype_burn.id,
        )
        result = handle_archetype(
            db, tg_id=1001, username="alice", first_name="Alice", last_name=None,
            tournament_id=active_tournament.id, archetype_id=archetype_burn.id,
        )
        assert result.text == ALREADY_REGISTERED
        assert result.is_alert

    def test_registration_closed_returns_alert(self, db, svc, active_tournament, archetype_burn):
        svc.close_tournament(active_tournament.id)
        result = handle_archetype(
            db, tg_id=1001, username="alice", first_name="Alice", last_name=None,
            tournament_id=active_tournament.id, archetype_id=archetype_burn.id,
        )
        assert result.text == REGISTRATION_CLOSED
        assert result.is_alert


# --- handle_custom_archetype_text ---

class TestHandleCustomArchetypeText:
    def test_registers_with_custom_archetype(self, db, active_tournament):
        result = handle_custom_archetype_text(
            db, tg_id=1001, username="alice", first_name="Alice", last_name=None,
            tournament_id=active_tournament.id, name="Turbo Fog",
        )
        assert result.text == REGISTERED
        assert not result.is_alert

    def test_already_registered_returns_message(self, db, active_tournament):
        handle_custom_archetype_text(
            db, tg_id=1001, username="alice", first_name="Alice", last_name=None,
            tournament_id=active_tournament.id, name="Turbo Fog",
        )
        result = handle_custom_archetype_text(
            db, tg_id=1001, username="alice", first_name="Alice", last_name=None,
            tournament_id=active_tournament.id, name="Turbo Fog",
        )
        assert result.text == ALREADY_REGISTERED

    def test_registration_closed(self, db, svc, active_tournament):
        svc.close_tournament(active_tournament.id)
        result = handle_custom_archetype_text(
            db, tg_id=1001, username="alice", first_name="Alice", last_name=None,
            tournament_id=active_tournament.id, name="Turbo Fog",
        )
        assert result.text == REGISTRATION_CLOSED


# --- handle_save_name_then_register ---

class TestHandleSaveNameThenRegister:
    def test_saves_name_and_returns_archetype_keyboard(self, db, svc, active_tournament, archetype_burn):
        from bot.handlers.player import handle_save_name_then_register
        result = handle_save_name_then_register(
            db, tg_id=7010, username="u", name_text="Иван Петров",
            tournament_id=active_tournament.id,
        )
        assert result.text == CHOOSE_ARCHETYPE
        assert result.keyboard is not None
        user = svc.get_user_by_tg_id(7010)
        assert user.first_name == "Иван"
        assert user.last_name == "Петров"

    def test_first_name_only(self, db, svc, active_tournament):
        from bot.handlers.player import handle_save_name_then_register
        handle_save_name_then_register(
            db, tg_id=7011, username=None, name_text="Мария",
            tournament_id=active_tournament.id,
        )
        user = svc.get_user_by_tg_id(7011)
        assert user.first_name == "Мария"
        assert user.last_name is None
