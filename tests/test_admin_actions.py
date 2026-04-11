"""Tests for admin handler business logic (handle_xxx functions)."""

import pytest
from core.schemas import TournamentCreate
from core.models import TournamentStatus
from bot.handlers.admin import (
    handle_add_me,
    handle_add_player,
    handle_add_players,
    handle_tournament_status,
    handle_close_tournament,
)
from bot.messages import (
    NOT_ADMIN,
    NO_DECK_NAME,
    NO_ACTIVE_TOURNAMENT,
    PLAYER_NOT_FOUND,
    PLAYER_ADDED,
    TOURNAMENT_CLOSED_MSG,
    ADD_PLAYERS_USAGE,
)

ADMIN_TG_ID = 9999
CHAT_ID = 100


@pytest.fixture
def admin_user(svc):
    u = svc.get_or_create_user(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin")
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


# --- handle_add_me ---

class TestHandleAddMe:
    def test_non_admin_returns_not_admin(self, db):
        result = handle_add_me(db, tg_id=42, username="x", first_name="X", last_name=None,
                               chat_id=CHAT_ID, deck_name="Burn")
        assert result.text == NOT_ADMIN

    def test_empty_deck_name_returns_usage(self, db, admin_user):
        result = handle_add_me(db, tg_id=ADMIN_TG_ID, username="admin", first_name="Admin",
                               last_name=None, chat_id=CHAT_ID, deck_name="")
        assert result.text == NO_DECK_NAME

    def test_no_active_tournament(self, db, admin_user):
        result = handle_add_me(db, tg_id=ADMIN_TG_ID, username="admin", first_name="Admin",
                               last_name=None, chat_id=CHAT_ID, deck_name="Burn")
        assert result.text == NO_ACTIVE_TOURNAMENT

    def test_registers_successfully(self, db, admin_user, active_tournament):
        result = handle_add_me(db, tg_id=ADMIN_TG_ID, username="admin", first_name="Admin",
                               last_name=None, chat_id=CHAT_ID, deck_name="Burn")
        assert "admin" in result.text
        assert "Burn" in result.text

    def test_already_registered(self, db, admin_user, active_tournament):
        handle_add_me(db, tg_id=ADMIN_TG_ID, username="admin", first_name="Admin",
                      last_name=None, chat_id=CHAT_ID, deck_name="Burn")
        result = handle_add_me(db, tg_id=ADMIN_TG_ID, username="admin", first_name="Admin",
                               last_name=None, chat_id=CHAT_ID, deck_name="Burn")
        assert "уже записаны" in result.text


# --- handle_add_player ---

class TestHandleAddPlayer:
    def test_non_admin_returns_not_admin(self, db, user_alice):
        result = handle_add_player(db, tg_id=42, chat_id=CHAT_ID,
                                   target_username="alice", deck_name="Burn")
        assert result.text == NOT_ADMIN

    def test_no_active_tournament(self, db, admin_user, user_alice):
        result = handle_add_player(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID,
                                   target_username="alice", deck_name="Burn")
        assert result.text == NO_ACTIVE_TOURNAMENT

    def test_player_not_found(self, db, admin_user, active_tournament):
        result = handle_add_player(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID,
                                   target_username="ghost", deck_name="Burn")
        assert "ghost" in result.text
        assert "не найден" in result.text

    def test_registers_player_successfully(self, db, admin_user, active_tournament, user_alice):
        result = handle_add_player(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID,
                                   target_username="alice", deck_name="Affinity")
        assert "alice" in result.text
        assert "Affinity" in result.text

    def test_already_registered(self, db, admin_user, active_tournament, user_alice):
        handle_add_player(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID,
                          target_username="alice", deck_name="Burn")
        result = handle_add_player(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID,
                                   target_username="alice", deck_name="Burn")
        assert "уже записан" in result.text


# --- handle_add_players ---

class TestHandleAddPlayers:
    def test_non_admin_returns_not_admin(self, db):
        result = handle_add_players(db, tg_id=42, chat_id=CHAT_ID, lines=["@alice Burn"])
        assert result.text == NOT_ADMIN

    def test_empty_lines_returns_usage(self, db, admin_user):
        result = handle_add_players(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID, lines=[])
        assert result.text == ADD_PLAYERS_USAGE

    def test_no_active_tournament(self, db, admin_user):
        result = handle_add_players(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID, lines=["@alice Burn"])
        assert result.text == NO_ACTIVE_TOURNAMENT

    def test_mixed_results(self, db, admin_user, active_tournament, user_alice, user_bob):
        lines = ["@alice Burn", "@ghost Affinity", "@bob"]
        result = handle_add_players(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID, lines=lines)
        assert "✅ @alice" in result.text
        assert "❌ @ghost" in result.text
        assert "⚠️ Пропущено" in result.text

    def test_already_registered_line(self, db, admin_user, active_tournament, user_alice):
        handle_add_player(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID,
                          target_username="alice", deck_name="Burn")
        result = handle_add_players(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID,
                                    lines=["@alice Burn"])
        assert "уже записан" in result.text


# --- handle_tournament_status ---

class TestHandleTournamentStatus:
    def test_non_admin_returns_not_admin(self, db):
        result = handle_tournament_status(db, tg_id=42, chat_id=CHAT_ID)
        assert result.text == NOT_ADMIN

    def test_no_active_tournament(self, db, admin_user):
        result = handle_tournament_status(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID)
        assert result.text == NO_ACTIVE_TOURNAMENT

    def test_shows_tournament_info(self, db, admin_user, active_tournament):
        result = handle_tournament_status(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID)
        assert "Weekly" in result.text
        assert "Участники" in result.text

    def test_shows_participants(self, db, svc, admin_user, active_tournament, user_alice, archetype_burn):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        result = handle_tournament_status(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID)
        assert "alice" in result.text
        assert "Burn" in result.text


# --- handle_close_tournament ---

class TestHandleCloseTournament:
    def test_non_admin_returns_not_admin(self, db):
        result = handle_close_tournament(db, tg_id=42, chat_id=CHAT_ID)
        assert result.text == NOT_ADMIN

    def test_no_active_tournament(self, db, admin_user):
        result = handle_close_tournament(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID)
        assert result.text == NO_ACTIVE_TOURNAMENT

    def test_closes_tournament(self, db, svc, admin_user, active_tournament):
        result = handle_close_tournament(db, tg_id=ADMIN_TG_ID, chat_id=CHAT_ID)
        assert result.text == TOURNAMENT_CLOSED_MSG
        # Verify it's actually closed
        closed = svc.get_active_tournament_for_chat(CHAT_ID)
        assert closed is None
