"""Tests for player handler business logic (PlayerHandler methods)."""

from datetime import timedelta

import pytest

from bot.handlers.player import DEFER_DECK_WINDOW, PlayerHandler
from bot.keyboards import (
    CB_ARCHETYPE,
    CB_CLOSE_TOURNAMENT,
    CB_CUSTOM_ARCHETYPE,
    CB_DEFER_DECK,
    CB_LEAVE,
    CB_REGISTER,
    CB_TSTATUS,
)
from bot.messages import (
    ALREADY_REGISTERED,
    CHOOSE_ARCHETYPE,
    DEFER_DECK_EXPIRED,
    LEAVE_CONFIRM_PROMPT,
    LEFT_TOURNAMENT,
    NO_ACTIVE_TOURNAMENTS,
    NOT_REGISTERED_IN_TOURNAMENT,
    REGISTERED,
    REGISTERED_AS,
    REGISTERED_DECK_LATER,
    REGISTRATION_CLOSED,
    TOURNAMENT_NOT_FOUND,
)
from core import models
from core.models import TournamentStatus, utc_now
from core.schemas import TournamentCreate

CHAT_ID = 200


@pytest.fixture
def active_tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Open", chat_id=CHAT_ID, slug="open"))


@pytest.fixture
def handler(svc, user_svc, arch_svc, keyboards, aetherhub_svc, features):
    return PlayerHandler(svc, user_svc, arch_svc, keyboards, aetherhub_svc, features)


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

    def test_scorekeeper_card_shows_close_button(self, handler, user_svc, active_tournament):
        scorekeeper = user_svc.get_or_create(tg_id=5101, username="keeper", first_name="Keeper")
        user_svc.toggle_scorekeeper(scorekeeper.tg_id)

        result = handler.handle_tournament_select(active_tournament.id, tg_id=scorekeeper.tg_id)

        callbacks = [button.callback_data for row in result.keyboard.inline_keyboard for button in row]
        assert f"{CB_CLOSE_TOURNAMENT}:{active_tournament.id}" in callbacks


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

    def test_shows_defer_button_during_first_seven_hours(self, handler, user_svc, active_tournament):
        user = user_svc.get_or_create(tg_id=5102, username="u", first_name="Иван")

        result = handler.handle_register(active_tournament.id, tg_id=user.tg_id)

        buttons = [button for row in result.keyboard.inline_keyboard for button in row]
        assert any(button.callback_data == f"{CB_DEFER_DECK}:{active_tournament.id}" for button in buttons)

    def test_hides_defer_button_after_seven_hours(self, db, handler, user_svc, active_tournament):
        user = user_svc.get_or_create(tg_id=5103, username="u", first_name="Иван")
        tournament = db.get(models.Tournament, active_tournament.id)
        tournament.created_at = utc_now() - DEFER_DECK_WINDOW - timedelta(seconds=1)
        db.commit()

        result = handler.handle_register(active_tournament.id, tg_id=user.tg_id)

        buttons = [button for row in result.keyboard.inline_keyboard for button in row]
        assert not any(button.callback_data.startswith(CB_DEFER_DECK) for button in buttons)

    def test_keeps_defer_button_until_future_scheduled_start(self, db, handler, user_svc, active_tournament):
        user = user_svc.get_or_create(tg_id=5104, username="u", first_name="Иван")
        tournament = db.get(models.Tournament, active_tournament.id)
        tournament.created_at = utc_now() - DEFER_DECK_WINDOW - timedelta(hours=1)
        tournament.registration_close_at = utc_now() + timedelta(hours=10)
        db.commit()

        result = handler.handle_register(active_tournament.id, tg_id=user.tg_id)

        buttons = [button for row in result.keyboard.inline_keyboard for button in row]
        assert any(button.callback_data == f"{CB_DEFER_DECK}:{active_tournament.id}" for button in buttons)


class TestHandleDeferDeck:
    def test_registers_without_deck_and_marks_explicit_defer(self, handler, svc, user_svc, active_tournament):
        result = handler.handle_defer_deck(
            tg_id=5201,
            username="later",
            first_name="Иван",
            last_name=None,
            tournament_id=active_tournament.id,
        )

        user = user_svc.get_by_tg_id(5201)
        participant = svc.get_participant(active_tournament.id, user.id)
        assert result.text == REGISTERED_DECK_LATER
        assert participant.archetype_id is None
        assert participant.deck_deferred is True

    def test_expired_defer_is_rejected_without_registration(self, db, handler, svc, user_svc, active_tournament):
        tournament = db.get(models.Tournament, active_tournament.id)
        tournament.created_at = utc_now() - DEFER_DECK_WINDOW
        db.commit()

        result = handler.handle_defer_deck(
            tg_id=5202,
            username="late",
            first_name="Иван",
            last_name=None,
            tournament_id=active_tournament.id,
        )

        assert result.text == DEFER_DECK_EXPIRED
        assert result.is_alert
        assert user_svc.get_by_tg_id(5202) is None

    def test_existing_deckless_participant_becomes_deferred(self, handler, svc, user_svc, active_tournament):
        user = user_svc.get_or_create(tg_id=5203, username="later", first_name="Иван")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id)

        result = handler.handle_defer_deck(
            tg_id=user.tg_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            tournament_id=active_tournament.id,
        )

        participant = svc.get_participant(active_tournament.id, user.id)
        assert result.text == REGISTERED_DECK_LATER
        assert participant.deck_deferred is True


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
        svc.register_participant(
            tournament_id=active_tournament.id,
            user_id=user.id,
            deck_deferred=True,
        )
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
        assert participant.deck_deferred is False

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

    def test_typo_registration_preserves_input_and_sets_separate_classification(
        self, handler, arch_svc, svc, active_tournament
    ):
        affinity = arch_svc.get_or_create_by_name("Grixis Affinity")

        handler.handle_custom_archetype_text(
            tg_id=1001,
            username="alice",
            first_name="Alice",
            last_name=None,
            tournament_id=active_tournament.id,
            name="Grixis Afinity",
        )

        participant = svc.list_participants_for_tournament(active_tournament.id)[0]
        assert participant.archetype_id != affinity.id
        assert participant.archetype.name == "Grixis Afinity"
        stored_archetype = svc.db.get(models.Archetype, participant.archetype_id)
        assert stored_archetype.general_name == "Grixis Affinity"
        assert stored_archetype.macro_name == "Affinity"

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


# --- deck_added_by_tg_id ---


class TestDeckAddedByTgId:
    def test_self_registration_sets_own_tg_id(self, handler, svc, user_svc, active_tournament, archetype_burn):
        handler.handle_archetype(
            tg_id=4001,
            username="player",
            first_name="Player",
            last_name=None,
            tournament_id=active_tournament.id,
            archetype_id=archetype_burn.id,
        )
        user = user_svc.get_by_tg_id(4001)
        p = svc.get_participant(active_tournament.id, user.id)
        assert p.deck_added_by_tg_id == 4001

    def test_update_own_deck_sets_own_tg_id(self, handler, svc, user_svc, active_tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=4002, username="player2", first_name="Player2")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id)
        handler.handle_archetype(
            tg_id=4002,
            username="player2",
            first_name="Player2",
            last_name=None,
            tournament_id=active_tournament.id,
            archetype_id=archetype_burn.id,
        )
        p = svc.get_participant(active_tournament.id, user.id)
        assert p.deck_added_by_tg_id == 4002

    def test_custom_archetype_sets_own_tg_id(self, handler, svc, user_svc, active_tournament):
        handler.handle_custom_archetype_text(
            tg_id=4003,
            username="player3",
            first_name="Player3",
            last_name=None,
            tournament_id=active_tournament.id,
            name="Storm",
        )
        user = user_svc.get_by_tg_id(4003)
        p = svc.get_participant(active_tournament.id, user.id)
        assert p.deck_added_by_tg_id == 4003
