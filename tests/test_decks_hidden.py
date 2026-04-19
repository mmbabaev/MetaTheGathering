"""Tests for decks_hidden feature: spoiler wrapping, reveal button, service method."""

import pytest
from core.schemas import TournamentCreate
from services.tournament import TournamentService
from bot.handlers.player import PlayerHandler
from bot.handlers.admin import AdminHandler
from bot.keyboards import CB_REVEAL_DECKS
from bot.messages import DECKS_REVEALED, format_tournament_status

CHAT_ID = 777


@pytest.fixture
def tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Hidden Cup", chat_id=CHAT_ID, slug="hidden"))


@pytest.fixture
def handler(svc, user_svc, arch_svc):
    return PlayerHandler(svc, user_svc, arch_svc)


@pytest.fixture
def admin_handler(svc, user_svc, arch_svc):
    return AdminHandler(svc, user_svc, arch_svc)


# ===== TournamentService.set_decks_hidden =====

class TestSetDecksHidden:
    def test_default_is_true(self, tournament):
        assert tournament.decks_hidden is True

    def test_set_false(self, svc, tournament):
        updated = svc.set_decks_hidden(tournament.id, hidden=False)
        assert updated.decks_hidden is False

    def test_set_true_again(self, svc, tournament):
        svc.set_decks_hidden(tournament.id, hidden=False)
        updated = svc.set_decks_hidden(tournament.id, hidden=True)
        assert updated.decks_hidden is True


# ===== format_tournament_status with decks_hidden =====

class TestFormatTournamentStatus:
    def test_hidden_wraps_archetype_in_spoiler(self, db, svc, user_svc, arch_svc, tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=4001, username="u", first_name="Ivan")
        svc.register_participant(tournament_id=tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        participants = svc.list_participants_for_tournament(tournament.id)

        text = format_tournament_status("T", "Регистрация", participants, decks_hidden=True)
        assert "<tg-spoiler>Burn</tg-spoiler>" in text
        assert "Burn" in text  # name still present inside tag

    def test_not_hidden_shows_plain_archetype(self, db, svc, user_svc, arch_svc, tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=4002, username="u2", first_name="Maria")
        svc.register_participant(tournament_id=tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        participants = svc.list_participants_for_tournament(tournament.id)

        text = format_tournament_status("T", "Регистрация", participants, decks_hidden=False)
        assert "<tg-spoiler>" not in text
        assert "Burn" in text

    def test_no_archetype_never_wrapped(self, db, svc, user_svc, tournament):
        user = user_svc.get_or_create(tg_id=4003, username="u3", first_name="Oleg")
        from core import models
        db.add(models.Participant(tournament_id=tournament.id, user_id=user.id))
        db.commit()
        participants = svc.list_participants_for_tournament(tournament.id)

        text = format_tournament_status("T", "Регистрация", participants, decks_hidden=True)
        assert "<tg-spoiler>" not in text
        assert "не указана" in text


# ===== PlayerHandler.handle_tournament_public_status =====

class TestHandleTournamentPublicStatus:
    def test_decks_hidden_returns_html_parse_mode(self, handler, svc, user_svc, arch_svc, tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=5001, username="p", first_name="Player")
        svc.register_participant(tournament_id=tournament.id, user_id=user.id, archetype_id=archetype_burn.id)

        result = handler.handle_tournament_public_status(tournament.id)
        assert result.parse_mode == "HTML"
        assert "<tg-spoiler>" in result.text

    def test_decks_revealed_no_parse_mode(self, handler, svc, user_svc, arch_svc, tournament, archetype_burn):
        svc.set_decks_hidden(tournament.id, hidden=False)
        user = user_svc.get_or_create(tg_id=5002, username="p2", first_name="Player2")
        svc.register_participant(tournament_id=tournament.id, user_id=user.id, archetype_id=archetype_burn.id)

        result = handler.handle_tournament_public_status(tournament.id)
        assert result.parse_mode is None
        assert "<tg-spoiler>" not in result.text
        assert "Burn" in result.text


# ===== Tournament card keyboard: reveal button =====

class TestTournamentCardKeyboard:
    def test_admin_sees_reveal_button_when_hidden(self, handler, user_svc, svc, arch_svc, tournament, archetype_burn):
        from unittest.mock import patch
        with patch("services.user.settings") as mock_settings:
            mock_settings.admin_ids = [9001]
            result = handler.handle_tournaments(tg_id=9001)

        buttons_flat = [btn for row in result.keyboard.inline_keyboard for btn in row]
        assert any(b.callback_data.startswith(CB_REVEAL_DECKS) for b in buttons_flat)

    def test_admin_no_reveal_button_when_already_revealed(self, handler, user_svc, svc, arch_svc, tournament):
        svc.set_decks_hidden(tournament.id, hidden=False)
        from unittest.mock import patch
        with patch("services.user.settings") as mock_settings:
            mock_settings.admin_ids = [9002]
            result = handler.handle_tournaments(tg_id=9002)

        buttons_flat = [btn for row in result.keyboard.inline_keyboard for btn in row]
        assert not any(b.callback_data.startswith(CB_REVEAL_DECKS) for b in buttons_flat)

    def test_non_admin_never_sees_reveal_button(self, handler, tournament):
        result = handler.handle_tournaments(tg_id=99999)
        buttons_flat = [btn for row in result.keyboard.inline_keyboard for btn in row]
        assert not any(b.callback_data.startswith(CB_REVEAL_DECKS) for b in buttons_flat)


# ===== AdminHandler.handle_reveal_decks =====

class TestHandleRevealDecks:
    def test_reveals_decks_and_returns_status(self, admin_handler, svc, user_svc, tournament, archetype_burn):
        from unittest.mock import patch
        user = user_svc.get_or_create(tg_id=6001, username="p", first_name="Player")
        svc.register_participant(tournament_id=tournament.id, user_id=user.id, archetype_id=archetype_burn.id)

        with patch("services.user.settings") as mock_settings:
            mock_settings.admin_ids = [8001]
            result = admin_handler.handle_reveal_decks(tg_id=8001, tournament_id=tournament.id)

        assert not result.is_alert
        assert DECKS_REVEALED in result.text
        updated = svc.get_active_tournament_for_chat(CHAT_ID)
        assert updated.decks_hidden is False

    def test_non_admin_returns_alert(self, admin_handler, tournament):
        from unittest.mock import patch
        with patch("services.user.settings") as mock_settings:
            mock_settings.admin_ids = []
            result = admin_handler.handle_reveal_decks(tg_id=99999, tournament_id=tournament.id)

        assert result.is_alert

    def test_tournament_not_found_returns_alert(self, admin_handler):
        from unittest.mock import patch
        with patch("services.user.settings") as mock_settings:
            mock_settings.admin_ids = [8001]
            result = admin_handler.handle_reveal_decks(tg_id=8001, tournament_id=99999)

        assert result.is_alert
