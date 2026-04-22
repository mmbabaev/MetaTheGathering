"""Tests for player handler business logic (PlayerHandler methods)."""

import pytest

from bot.handlers.player import PlayerHandler
from bot.keyboards import CB_ARCHETYPE, CB_CUSTOM_ARCHETYPE, CB_LEAVE, CB_REGISTER, CB_TSTATUS
from bot.messages import (
    ALREADY_REGISTERED,
    CHOOSE_ARCHETYPE,
    LEAVE_CONFIRM_PROMPT,
    LEFT_TOURNAMENT,
    NO_ACTIVE_TOURNAMENTS,
    NOT_REGISTERED_IN_TOURNAMENT,
    REGISTERED,
    REGISTERED_AS,
    REGISTRATION_CLOSED,
    TOURNAMENT_NOT_FOUND,
)
from core.models import TournamentStatus, utc_now
from core.schemas import TournamentCreate

CHAT_ID = 200


@pytest.fixture
def active_tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Open", chat_id=CHAT_ID, slug="open"))


@pytest.fixture
def handler(svc, user_svc, arch_svc):
    return PlayerHandler(svc, user_svc, arch_svc)


# --- handle_tournaments ---


class TestHandleTournaments:
    def test_no_tournaments_returns_message(self, handler):
        result = handler.handle_tournaments()
        assert result.text == NO_ACTIVE_TOURNAMENTS
        assert result.keyboard is None

    def test_single_tournament_returns_card_with_register_button(self, handler, active_tournament):
        result = handler.handle_tournaments()
        assert "Open" in result.text
        assert result.keyboard is not None

    def test_multiple_tournaments_returns_list(self, db, handler):
        from core import models

        for i, slug in enumerate(("t1", "t2"), start=1):
            db.add(
                models.Tournament(
                    title=slug.upper(),
                    chat_id=CHAT_ID + i,
                    slug=slug,
                    status=models.TournamentStatus.REGISTRATION,
                    created_at=utc_now(),
                )
            )
        db.commit()
        result = handler.handle_tournaments()
        assert "Выберите турнир" in result.text
        assert result.keyboard is not None

    def test_closed_tournament_not_shown(self, handler, svc, active_tournament):
        svc.close_tournament(active_tournament.id)
        result = handler.handle_tournaments()
        assert result.text == NO_ACTIVE_TOURNAMENTS

    def test_shows_tournaments_from_all_chats(self, handler, svc, active_tournament):
        """Турниры из разных чатов видны в общем списке."""
        svc.create_tournament(TournamentCreate(title="Other Chat", chat_id=CHAT_ID + 1, slug="other"))
        result = handler.handle_tournaments()
        assert "Выберите турнир" in result.text


# --- handle_tournament_select ---


class TestHandleTournamentSelect:
    def test_valid_tournament_returns_card(self, handler, active_tournament):
        result = handler.handle_tournament_select(active_tournament.id)
        assert "Open" in result.text
        assert result.keyboard is not None
        assert not result.is_alert

    def test_not_found_returns_alert(self, handler):
        result = handler.handle_tournament_select(tournament_id=99999)
        assert result.text == TOURNAMENT_NOT_FOUND
        assert result.is_alert


# --- handle_register ---


class TestHandleRegister:
    def test_returns_archetype_choice_no_tg_id(self, handler, active_tournament, archetype_burn, archetype_affinity):
        result = handler.handle_register(active_tournament.id)
        assert result.text == CHOOSE_ARCHETYPE
        assert result.keyboard is not None
        assert not result.needs_name

    def test_returns_archetype_choice_when_user_has_name(self, handler, user_svc, active_tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=5100, username="u", first_name="Иван")
        result = handler.handle_register(active_tournament.id, tg_id=user.tg_id)
        assert result.text == CHOOSE_ARCHETYPE
        assert result.keyboard is not None
        assert not result.needs_name

    def test_needs_name_when_user_has_no_name(self, handler, user_svc, active_tournament):
        user = user_svc.get_or_create(tg_id=5101, username="u", first_name=None)
        result = handler.handle_register(active_tournament.id, tg_id=user.tg_id)
        assert result.needs_name is True
        assert result.keyboard is None

    def test_needs_name_when_user_unknown(self, handler, active_tournament):
        result = handler.handle_register(active_tournament.id, tg_id=99999)
        assert result.needs_name is True


# --- handle_archetype ---


class TestHandleArchetype:
    def test_registers_successfully(self, handler, active_tournament, archetype_burn):
        result = handler.handle_archetype(
            tg_id=1001,
            username="alice",
            first_name="Alice",
            last_name=None,
            tournament_id=active_tournament.id,
            archetype_id=archetype_burn.id,
        )
        assert "Burn" in result.text
        assert not result.is_alert

    def test_already_registered_with_deck_returns_alert(self, handler, active_tournament, archetype_burn):
        handler.handle_archetype(
            tg_id=1001,
            username="alice",
            first_name="Alice",
            last_name=None,
            tournament_id=active_tournament.id,
            archetype_id=archetype_burn.id,
        )
        result = handler.handle_archetype(
            tg_id=1001,
            username="alice",
            first_name="Alice",
            last_name=None,
            tournament_id=active_tournament.id,
            archetype_id=archetype_burn.id,
        )
        assert result.text == ALREADY_REGISTERED
        assert result.is_alert

    def test_already_registered_without_deck_updates_archetype(
        self, handler, svc, user_svc, active_tournament, archetype_burn
    ):
        user = user_svc.get_or_create(tg_id=1001, username="alice", first_name="Alice")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id)
        result = handler.handle_archetype(
            tg_id=1001,
            username="alice",
            first_name="Alice",
            last_name=None,
            tournament_id=active_tournament.id,
            archetype_id=archetype_burn.id,
        )
        assert "Burn" in result.text
        assert not result.is_alert
        participant = svc.get_participant(active_tournament.id, user.id)
        assert participant.archetype_id == archetype_burn.id

    def test_registration_closed_returns_alert(self, handler, svc, active_tournament, archetype_burn):
        svc.close_tournament(active_tournament.id)
        result = handler.handle_archetype(
            tg_id=1001,
            username="alice",
            first_name="Alice",
            last_name=None,
            tournament_id=active_tournament.id,
            archetype_id=archetype_burn.id,
        )
        assert result.text == REGISTRATION_CLOSED
        assert result.is_alert


# --- handle_custom_archetype_text ---


class TestHandleCustomArchetypeText:
    def test_registers_with_custom_archetype(self, handler, active_tournament):
        result = handler.handle_custom_archetype_text(
            tg_id=1001,
            username="alice",
            first_name="Alice",
            last_name=None,
            tournament_id=active_tournament.id,
            name="Turbo Fog",
        )
        assert result.text == REGISTERED
        assert not result.is_alert

    def test_already_registered_returns_message(self, handler, active_tournament):
        handler.handle_custom_archetype_text(
            tg_id=1001,
            username="alice",
            first_name="Alice",
            last_name=None,
            tournament_id=active_tournament.id,
            name="Turbo Fog",
        )
        result = handler.handle_custom_archetype_text(
            tg_id=1001,
            username="alice",
            first_name="Alice",
            last_name=None,
            tournament_id=active_tournament.id,
            name="Turbo Fog",
        )
        assert result.text == ALREADY_REGISTERED

    def test_registration_closed(self, handler, svc, active_tournament):
        svc.close_tournament(active_tournament.id)
        result = handler.handle_custom_archetype_text(
            tg_id=1001,
            username="alice",
            first_name="Alice",
            last_name=None,
            tournament_id=active_tournament.id,
            name="Turbo Fog",
        )
        assert result.text == REGISTRATION_CLOSED


# --- handle_save_name_then_register ---


class TestHandleSaveNameThenRegister:
    def test_saves_name_and_returns_archetype_keyboard(self, handler, user_svc, active_tournament, archetype_burn):
        result = handler.handle_save_name_then_register(
            tg_id=7010,
            username="u",
            name_text="Петров Иван",
            tournament_id=active_tournament.id,
        )
        assert result.text == CHOOSE_ARCHETYPE
        assert result.keyboard is not None
        user = user_svc.get_by_tg_id(7010)
        assert user.first_name == "Иван"
        assert user.last_name == "Петров"

    def test_first_name_only(self, handler, user_svc, active_tournament):
        handler.handle_save_name_then_register(
            tg_id=7011,
            username=None,
            name_text="Мария",
            tournament_id=active_tournament.id,
        )
        user = user_svc.get_by_tg_id(7011)
        assert user.first_name == "Мария"
        assert user.last_name is None


# --- handle_tournaments: dynamic keyboard ---


class TestHandleTournamentsDynamicKeyboard:
    def test_unregistered_user_gets_register_button(self, handler, active_tournament):
        result = handler.handle_tournaments(tg_id=99999)
        assert result.keyboard is not None
        cb = result.keyboard.inline_keyboard[0][0].callback_data
        assert cb.startswith(CB_REGISTER)

    def test_registered_user_gets_leave_button(self, handler, svc, user_svc, active_tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=3001, username="p", first_name="Player")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_tournaments(tg_id=3001)
        assert result.keyboard is not None
        cb = result.keyboard.inline_keyboard[0][0].callback_data
        assert cb.startswith(CB_LEAVE)

    def test_both_statuses_have_status_button(self, handler, active_tournament):
        result = handler.handle_tournaments(tg_id=None)
        buttons_flat = [btn for row in result.keyboard.inline_keyboard for btn in row]
        assert any(b.callback_data.startswith(CB_TSTATUS) for b in buttons_flat)


# --- handle_tournament_public_status ---


class TestHandleTournamentPublicStatus:
    def test_shows_tournament_info(self, handler, active_tournament):
        result = handler.handle_tournament_public_status(active_tournament.id)
        assert "Open" in result.text
        assert not result.is_alert

    def test_shows_participants(self, handler, svc, user_svc, active_tournament, archetype_burn):
        svc.set_decks_hidden(active_tournament.id, hidden=False)
        user = user_svc.get_or_create(tg_id=3010, username=None, first_name="Алиса")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_tournament_public_status(active_tournament.id)
        assert "Алиса" in result.text
        assert "Burn" in result.text

    def test_not_found_returns_alert(self, handler):
        result = handler.handle_tournament_public_status(tournament_id=99999)
        assert result.is_alert
        assert result.text == TOURNAMENT_NOT_FOUND


# --- handle_leave_tournament / handle_leave_confirm ---


class TestHandleLeaveTournament:
    def test_unknown_user_returns_alert(self, handler, active_tournament):
        result = handler.handle_leave_tournament(tg_id=99999, tournament_id=active_tournament.id)
        assert result.is_alert
        assert result.text == NOT_REGISTERED_IN_TOURNAMENT

    def test_known_user_not_participant_returns_alert(self, handler, user_svc, active_tournament):
        user_svc.get_or_create(tg_id=3025, username="p", first_name="Player")
        result = handler.handle_leave_tournament(tg_id=3025, tournament_id=active_tournament.id)
        assert result.is_alert
        assert result.text == NOT_REGISTERED_IN_TOURNAMENT

    def test_registered_returns_confirmation(self, handler, svc, user_svc, active_tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=3020, username="p", first_name="Player")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_leave_tournament(tg_id=3020, tournament_id=active_tournament.id)
        assert result.text == LEAVE_CONFIRM_PROMPT
        assert result.keyboard is not None
        assert not result.is_alert


class TestHandleLeaveConfirm:
    def test_removes_participant(self, handler, svc, user_svc, active_tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=3030, username="p", first_name="Player")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_leave_confirm(tg_id=3030, tournament_id=active_tournament.id)
        assert result.text == LEFT_TOURNAMENT
        assert not result.is_alert
        # Verify actually removed
        assert svc.get_participant(active_tournament.id, user.id) is None

    def test_unknown_user_returns_alert(self, handler, active_tournament):
        result = handler.handle_leave_confirm(tg_id=99999, tournament_id=active_tournament.id)
        assert result.is_alert
        assert result.text == NOT_REGISTERED_IN_TOURNAMENT

    def test_known_user_not_participant_returns_alert(self, handler, user_svc, active_tournament):
        user_svc.get_or_create(tg_id=3035, username="p", first_name="Player")
        result = handler.handle_leave_confirm(tg_id=3035, tournament_id=active_tournament.id)
        assert result.is_alert
        assert result.text == NOT_REGISTERED_IN_TOURNAMENT

    def test_can_reregister_after_leaving(self, handler, svc, user_svc, active_tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=3031, username="p", first_name="Player")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        handler.handle_leave_confirm(tg_id=3031, tournament_id=active_tournament.id)
        # Re-register
        result = handler.handle_archetype(
            tg_id=3031,
            username="p",
            first_name="Player",
            last_name=None,
            tournament_id=active_tournament.id,
            archetype_id=archetype_burn.id,
        )
        assert "Burn" in result.text
        assert not result.is_alert
