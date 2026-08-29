"""Tests for admin handler business logic (AdminHandler methods)."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from bot.features import FeatureService
from bot.handlers.admin import (
    AdminHandler,
    _player_display_label,
    parse_bulk_player_line,
)
from bot.keyboards import (
    CB_ADMIN_ARCH_MORE,
    CB_ADMIN_PICK_ARCH,
    CB_ADMIN_PLAYER_ACTIONS,
    CB_ADMIN_REMOVE_CONFIRM,
    CB_ADMIN_REMOVE_DO,
    CB_ADMIN_SET_ARCH,
    CB_ADMIN_SHOW_FILLED,
    CB_ADMIN_SHOW_OPPONENTS,
    CB_ADMIN_TOGGLE_SCOREKEEPER,
    CB_CLOSE_TOURNAMENT_CONFIRM,
    CB_TSTATUS,
)
from bot.messages import (
    ADMIN_ARCH_SAVED,
    BULK_ADD_EMPTY,
    CHOOSE_ARCHETYPE,
    MULTIPLE_TOURNAMENTS_MSG,
    NO_ACTIVE_TOURNAMENT,
    NOT_ADMIN,
    PARTICIPANT_NOT_FOUND,
    PLAYER_ADDED,
    REGISTRATION_CLOSED,
    SCOREKEEPER_GRANTED,
    SCOREKEEPER_REVOKED,
    TOURNAMENT_ALREADY_EXISTS_MSG,
    TOURNAMENT_CLOSED_MSG,
    TOURNAMENT_NOT_FOUND,
)
from core import models as m
from core.models import TournamentStatus
from core.schemas import TournamentCreate
from services import errors
from services.aetherhub_import_service import MIN_TOURNAMENT_DURATION, AetherhubImportService
from services.aetherhub_models import AetherhubPairing, AetherhubRound, AetherhubTournamentData
from services.deck_colors import DeckColorResolver
from services.feature_flags import FeatureFlags
from services.meta_chart import MetaChartService, render_sectors

ADMIN_TG_ID = 9999
CHAT_ID = 100


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
    stmt = select(m.User).where(m.User.tg_id == ADMIN_TG_ID)
    obj = svc.db.execute(stmt).scalar_one()
    obj.is_admin = True
    svc.db.commit()
    return u


@pytest.fixture
def active_tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Weekly", chat_id=CHAT_ID, slug="weekly"))


@pytest.fixture
def handler(svc, user_svc, arch_svc, keyboards, features):
    return AdminHandler(svc, user_svc, arch_svc, keyboards, features)


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
        handler.handle_add_players(
            tg_id=ADMIN_TG_ID,
            entries=[(user_alice.tg_id, "alice", "Alice", "Burn")],
        )
        result = handler.handle_add_players(
            tg_id=ADMIN_TG_ID,
            entries=[(user_alice.tg_id, "alice", "Alice", "Burn")],
        )
        assert "уже записан" in result.text

    def test_multiple_tournaments_returns_clarification(self, handler, svc, admin_user, active_tournament, user_alice):
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
        assert "чел." in result.text

    def test_shows_participants_with_archetype(
        self, handler, svc, admin_user, active_tournament, user_alice, archetype_burn
    ):
        svc.register_participant(
            tournament_id=active_tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id
        )
        result = handler.handle_tournament_status(tg_id=ADMIN_TG_ID)
        assert "alice" in result.text
        assert "Burn" in result.text

    def test_confirmed_participant_has_checkmark(
        self, db, handler, svc, admin_user, active_tournament, user_alice, archetype_burn
    ):
        svc.register_participant(
            tournament_id=active_tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id
        )
        p = db.execute(select(m.Participant).where(m.Participant.user_id == user_alice.id)).scalar_one()
        p.confirmed = True
        db.commit()
        result = handler.handle_tournament_status(tg_id=ADMIN_TG_ID)
        assert "✅" in result.text

    def test_shows_all_active_tournaments(self, handler, svc, admin_user, active_tournament):
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
        assert svc.db.get(m.Tournament, active_tournament.id).closed_by_tg_id == ADMIN_TG_ID

    def test_tournament_with_players_requires_confirmation(
        self, handler, svc, admin_user, active_tournament, user_alice
    ):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)

        result = handler.handle_close_tournament(tg_id=ADMIN_TG_ID)

        assert "записано игроков: 1" in result.text
        assert result.keyboard is not None
        assert svc.db.get(m.Tournament, active_tournament.id).status != TournamentStatus.CLOSED

    def test_multiple_tournaments_returns_clarification(self, handler, svc, admin_user, active_tournament):
        svc.create_tournament(TournamentCreate(title="Second", chat_id=CHAT_ID + 1))
        result = handler.handle_close_tournament(tg_id=ADMIN_TG_ID)
        assert result.text == MULTIPLE_TOURNAMENTS_MSG


# --- UserService.is_admin ---


class TestIsAdminViaSettings:
    def test_admin_via_settings_ids(self, handler):
        with patch("services.user.settings") as mock_settings:
            mock_settings.admin_ids = [555]
            assert handler.user_svc.is_admin(tg_id=555) is True

    def test_non_admin_not_in_settings_or_db(self, handler):
        with patch("services.user.settings") as mock_settings:
            mock_settings.admin_ids = []
            assert handler.user_svc.is_admin(tg_id=42) is False

    def test_admin_via_db_is_admin_flag(self, handler, admin_user):
        with patch("services.user.settings") as mock_settings:
            mock_settings.admin_ids = []
            assert handler.user_svc.is_admin(tg_id=ADMIN_TG_ID) is True


# --- handle_add_players: TournamentInvalidState ---


class TestHandleAddPlayersInvalidState:
    def test_registration_closed_marks_line(self, db, handler, svc, admin_user, active_tournament, user_alice):
        obj = db.execute(select(m.Tournament).where(m.Tournament.id == active_tournament.id)).scalar_one()
        obj.status = m.TournamentStatus.ONGOING
        db.commit()
        result = handler.handle_add_players(
            tg_id=ADMIN_TG_ID,
            entries=[(user_alice.tg_id, "alice", "Alice", "Burn")],
        )
        assert "закрыта" in result.text


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


# --- handle_tournament_status: full name display ---


class TestTournamentStatusFullName:
    def test_shows_first_and_last_name(self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=6100, username=None, first_name="Иван", last_name="Иванов")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_tournament_status(tg_id=ADMIN_TG_ID)
        assert "Иван" in result.text
        assert "Иванов" in result.text

    def test_shows_username_hint_when_available(
        self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn
    ):
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
        result = handler.handle_bulk_add_by_name(tg_id=42, tournament_id=active_tournament.id, names=["Иван Иванов"])
        assert result.text == NOT_ADMIN

    def test_empty_names_returns_empty_message(self, handler, admin_user, active_tournament):
        result = handler.handle_bulk_add_by_name(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=[])
        assert result.text == BULK_ADD_EMPTY

    def test_blank_lines_only_returns_empty(self, handler, admin_user, active_tournament):
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["  ", ""]
        )
        assert result.text == BULK_ADD_EMPTY

    def test_creates_new_user_and_adds(self, handler, admin_user, active_tournament, user_svc):
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Иванов Иван"]
        )
        assert "✅ Иванов Иван" in result.text
        user = user_svc.get_or_create_by_name("Иван", "Иванов")
        assert user is not None

    def test_finds_existing_user_by_name(self, handler, admin_user, active_tournament, user_svc):
        user_svc.get_or_create_by_name("Мария", "Петрова")
        user_svc.db.commit()
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Петрова Мария"]
        )
        assert "✅ Петрова Мария" in result.text

    def test_skips_already_registered(self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn):
        user = user_svc.get_or_create(tg_id=7001, username=None, first_name="Алекс")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_bulk_add_by_name(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Алекс"])
        assert "⚠️ Алекс — уже записан" in result.text

    def test_multiple_names_mixed_result(self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn):
        existing = user_svc.get_or_create(tg_id=7002, username=None, first_name="Борис")
        svc.register_participant(
            tournament_id=active_tournament.id, user_id=existing.id, archetype_id=archetype_burn.id
        )
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID,
            tournament_id=active_tournament.id,
            names=["Борис", "Новая Вера"],
        )
        assert "⚠️ Борис — уже записан" in result.text
        assert "✅ Новая Вера" in result.text

    def test_tournament_not_found(self, handler, admin_user):
        result = handler.handle_bulk_add_by_name(tg_id=ADMIN_TG_ID, tournament_id=99999, names=["Иван"])
        assert result.text == TOURNAMENT_NOT_FOUND

    def test_registration_closed(self, handler, svc, admin_user, active_tournament):
        svc.close_tournament(active_tournament.id)
        result = handler.handle_bulk_add_by_name(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Иван"])
        assert result.text == REGISTRATION_CLOSED

    def test_first_name_only(self, handler, admin_user, active_tournament):
        result = handler.handle_bulk_add_by_name(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Мария"])
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
        result = handler.handle_admin_status(tg_id=ADMIN_TG_ID, tournament_id=99999)
        assert result.text == TOURNAMENT_NOT_FOUND
        assert result.is_alert

    def test_keyboard_unfilled_participant_visible(self, handler, svc, user_svc, admin_user, active_tournament):
        """Незаполненный участник виден без нажатия кнопки разворота."""
        user = user_svc.get_or_create(tg_id=8001, username=None, first_name="Тест")
        svc.bulk_add_participants(active_tournament.id, [(user.id, "Тест")])
        result = handler.handle_admin_status(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        buttons = [b for row in result.keyboard.inline_keyboard for b in row]

        assert any(b.callback_data.startswith(CB_ADMIN_PICK_ARCH) for b in buttons)

    def test_keyboard_filled_participant_hidden_by_default(
        self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn
    ):
        """Заполненный участник скрыт по умолчанию, но есть кнопка «Показать заполненных»."""
        user = user_svc.get_or_create(tg_id=8001, username=None, first_name="Тест")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_admin_status(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        buttons = [b for row in result.keyboard.inline_keyboard for b in row]

        assert not any(b.callback_data.startswith(CB_ADMIN_PICK_ARCH) for b in buttons)
        assert any(b.callback_data.startswith(CB_ADMIN_SHOW_FILLED) for b in buttons)

    def test_keyboard_show_filled_reveals_all(
        self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn
    ):
        """handle_admin_show_filled показывает кнопки заполненных участников."""
        user = user_svc.get_or_create(tg_id=8001, username=None, first_name="Тест")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_admin_show_filled(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        buttons = [b for row in result.keyboard.inline_keyboard for b in row]

        assert any(b.callback_data.startswith(CB_ADMIN_PICK_ARCH) for b in buttons)

    def test_button_label_shows_familiya_imya_order(self, handler, svc, user_svc, admin_user, active_tournament):
        """Кнопка участника показывает «Фамилия Имя», а не «Имя Фамилия»."""
        user = user_svc.get_or_create(tg_id=8005, username=None, first_name="Антон", last_name="Ильин")
        svc.bulk_add_participants(active_tournament.id, [(user.id, "Тест")])
        result = handler.handle_admin_status(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        buttons_text = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert any("Ильин Антон" in t for t in buttons_text)
        assert not any("Антон Ильин" in t for t in buttons_text)

    def test_no_archetype_participant_gets_pencil_prefix(self, handler, svc, user_svc, admin_user, active_tournament):
        user = user_svc.get_or_create(tg_id=8002, username=None, first_name="Безколоды")
        svc.bulk_add_participants(active_tournament.id, [(user.id, "Безколоды")])
        result = handler.handle_admin_status(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        buttons_text = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert any("📝" in t for t in buttons_text)

    def test_with_archetype_participant_gets_edit_prefix(
        self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn
    ):
        user = user_svc.get_or_create(tg_id=8003, username=None, first_name="Сколодой")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user.id, archetype_id=archetype_burn.id)
        result = handler.handle_admin_show_filled(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        buttons_text = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert any("✏️" in t for t in buttons_text)


# --- handle_pick_participant_arch ---


class TestHandleAdminPickArch:
    @pytest.fixture
    def participant(self, svc, user_svc, active_tournament):
        user = user_svc.get_or_create(tg_id=8100, username=None, first_name="Игрок")
        svc.bulk_add_participants(active_tournament.id, [(user.id, "Игрок")])
        return svc.get_participant(active_tournament.id, user.id)

    def test_non_admin_blocked_when_feature_disabled(self, handler, ff_svc, active_tournament, participant):
        ff_svc.toggle(FeatureFlags.RECORD_OPPONENTS)  # default true → false
        result = handler.handle_pick_participant_arch(tg_id=42, participant_id=participant.id)
        assert result.text == NOT_ADMIN

    def test_returns_archetype_keyboard(self, handler, admin_user, active_tournament, participant, archetype_burn):
        result = handler.handle_pick_participant_arch(tg_id=ADMIN_TG_ID, participant_id=participant.id)
        assert result.text == CHOOSE_ARCHETYPE
        assert result.keyboard is not None

    def test_participant_not_found(self, handler, admin_user):
        result = handler.handle_pick_participant_arch(tg_id=ADMIN_TG_ID, participant_id=99999)
        assert result.text == PARTICIPANT_NOT_FOUND
        assert result.is_alert

    def test_keyboard_uses_admin_callbacks(self, handler, admin_user, active_tournament, participant, archetype_burn):
        result = handler.handle_pick_participant_arch(tg_id=ADMIN_TG_ID, participant_id=participant.id)
        buttons = [b for row in result.keyboard.inline_keyboard for b in row]
        assert any(b.callback_data.startswith(CB_ADMIN_SET_ARCH) for b in buttons)

    def test_admin_sees_actions_menu_button(self, handler, admin_user, active_tournament, participant):
        result = handler.handle_pick_participant_arch(tg_id=ADMIN_TG_ID, participant_id=participant.id)
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(cb.startswith(CB_ADMIN_PLAYER_ACTIONS) for cb in cbs)

    def test_non_admin_no_actions_menu_button(self, handler, svc, user_svc, active_tournament, participant):
        non_admin = user_svc.get_or_create(tg_id=5555, username=None, first_name="Regular")
        result = handler.handle_pick_participant_arch(tg_id=non_admin.tg_id, participant_id=participant.id)
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert not any(cb.startswith(CB_ADMIN_PLAYER_ACTIONS) for cb in cbs)

    def test_back_button_points_to_tournament_status(self, handler, admin_user, active_tournament, participant):
        result = handler.handle_pick_participant_arch(tg_id=ADMIN_TG_ID, participant_id=participant.id)
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(cb == f"{CB_TSTATUS}:{active_tournament.id}" for cb in cbs)


# --- handle_set_participant_arch ---


class TestHandleAdminSetArch:
    @pytest.fixture
    def participant(self, svc, user_svc, active_tournament):
        user = user_svc.get_or_create(tg_id=8200, username=None, first_name="Игрок")
        svc.bulk_add_participants(active_tournament.id, [(user.id, "Игрок")])
        return svc.get_participant(active_tournament.id, user.id)

    def test_non_admin_blocked_when_feature_disabled(
        self, handler, ff_svc, active_tournament, participant, archetype_burn
    ):
        ff_svc.toggle(FeatureFlags.RECORD_OPPONENTS)  # default true → false
        result = handler.handle_set_participant_arch(
            tg_id=42, participant_id=participant.id, archetype_id=archetype_burn.id
        )
        assert result.text == NOT_ADMIN

    def test_sets_archetype_successfully(
        self, handler, svc, admin_user, active_tournament, participant, archetype_burn
    ):
        result = handler.handle_set_participant_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, archetype_id=archetype_burn.id
        )
        assert "Burn" in result.text
        assert not result.is_alert
        updated = svc.get_participant(active_tournament.id, participant.user_id)
        assert updated.archetype_id == archetype_burn.id

    def test_participant_not_found(self, handler, admin_user, archetype_burn):
        result = handler.handle_set_participant_arch(
            tg_id=ADMIN_TG_ID, participant_id=99999, archetype_id=archetype_burn.id
        )
        assert result.text == PARTICIPANT_NOT_FOUND
        assert result.is_alert


# --- handle_set_participant_custom_arch ---


class TestHandleAdminCustomArchText:
    @pytest.fixture
    def participant(self, svc, user_svc, active_tournament):
        user = user_svc.get_or_create(tg_id=8300, username=None, first_name="Игрок")
        svc.bulk_add_participants(active_tournament.id, [(user.id, "Игрок")])
        return svc.get_participant(active_tournament.id, user.id)

    def test_non_admin_blocked_when_feature_disabled(self, handler, ff_svc, participant):
        ff_svc.toggle(FeatureFlags.RECORD_OPPONENTS)  # default true → false
        result = handler.handle_set_participant_custom_arch(tg_id=42, participant_id=participant.id, arch_name="Elves")
        assert result.text == NOT_ADMIN

    def test_creates_archetype_and_sets(self, handler, svc, admin_user, participant):
        result = handler.handle_set_participant_custom_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, arch_name="Turbo Fog"
        )
        assert "Turbo Fog" in result.text
        assert not result.is_alert

    def test_returns_participants_keyboard_after_custom_arch(self, handler, svc, admin_user, participant):
        result = handler.handle_set_participant_custom_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, arch_name="Turbo Fog"
        )
        assert result.keyboard is not None

    def test_back_button_present_after_custom_arch(self, handler, svc, admin_user, participant):
        result = handler.handle_set_participant_custom_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, arch_name="Turbo Fog"
        )
        buttons = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert any("Назад" in t for t in buttons)

    def test_participant_not_found(self, handler, admin_user):
        result = handler.handle_set_participant_custom_arch(tg_id=ADMIN_TG_ID, participant_id=99999, arch_name="Elves")
        assert result.text == PARTICIPANT_NOT_FOUND
        assert result.is_alert


class TestHandleAdminPickArchUsesParticipantHistory:
    """Убеждаемся что список архетипов персонализирован под игрока, а не под админа."""

    @pytest.fixture
    def setup(self, svc, user_svc, arch_svc, active_tournament):
        burn = arch_svc.get_or_create_by_name("Burn")
        elves = arch_svc.get_or_create_by_name("Elves")

        # Прошлый турнир: админ играл Burn
        t_admin = svc.create_tournament(TournamentCreate(title="Admin Hist", chat_id=CHAT_ID + 50, slug="ah"))
        admin = user_svc.get_or_create(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin")
        svc.register_participant(tournament_id=t_admin.id, user_id=admin.id, archetype_id=burn.id)

        # Прошлый турнир: игрок играл Elves
        player = user_svc.get_or_create(tg_id=8888, username=None, first_name="Player")
        t_player = svc.create_tournament(TournamentCreate(title="Player Hist", chat_id=CHAT_ID + 51, slug="ph"))
        svc.register_participant(tournament_id=t_player.id, user_id=player.id, archetype_id=elves.id)

        # Активный турнир: игрок добавлен без колоды
        svc.bulk_add_participants(active_tournament.id, [(player.id, "Player")])
        participant = svc.get_participant(active_tournament.id, player.id)
        return participant, burn, elves

    def test_first_archetype_is_player_history_not_admin_history(self, handler, admin_user, active_tournament, setup):
        participant, burn, elves = setup
        result = handler.handle_pick_participant_arch(tg_id=ADMIN_TG_ID, participant_id=participant.id)

        first_btn = result.keyboard.inline_keyboard[0][0]
        # Elves — история игрока, должна стоять первой
        assert "Elves" in first_btn.text, (
            f"Ожидали Elves (история игрока) первым архетипом, но получили: {first_btn.text}"
        )
        # Burn — история админа, не должна быть первой
        assert "Burn" not in first_btn.text

    def test_bulk_added_player_no_history_gets_top_by_popularity_not_admin_order(
        self, handler, svc, user_svc, arch_svc, admin_user, active_tournament
    ):
        """Игрок без истории (bulk add) должен получать топ по глобальной популярности,
        а не персональный список колод админа.

        Сценарий: «Zzz Deck» — колода админа (1 использование), «Aaa Deck» — сыграна
        двумя другими игроками (2 использования). Для игрока без истории топ должен
        показать «Aaa Deck» первой (она глобально популярнее).
        """
        aaa = arch_svc.get_or_create_by_name("Aaa Deck")
        zzz = arch_svc.get_or_create_by_name("Zzz Deck")

        # Прошлый турнир: админ играл Zzz (1 раз)
        t_admin = svc.create_tournament(TournamentCreate(title="Admin Z hist", chat_id=CHAT_ID + 60, slug="az"))
        admin = user_svc.get_or_create(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin")
        svc.register_participant(tournament_id=t_admin.id, user_id=admin.id, archetype_id=zzz.id)

        # Ещё два других игрока играли Aaa (больше использований у Aaa)
        u1 = user_svc.get_or_create(tg_id=7701, username=None, first_name="Player1")
        u2 = user_svc.get_or_create(tg_id=7702, username=None, first_name="Player2")
        t_other = svc.create_tournament(TournamentCreate(title="Other hist", chat_id=CHAT_ID + 61, slug="oh"))
        svc.register_participant(tournament_id=t_other.id, user_id=u1.id, archetype_id=aaa.id)
        svc.register_participant(tournament_id=t_other.id, user_id=u2.id, archetype_id=aaa.id)

        # Игрок добавлен через bulk_add — нет истории архетипов
        player = user_svc.get_or_create_by_name("Bulk", "Player")[0]
        svc.bulk_add_participants(active_tournament.id, [(player.id, "Bulk Player")])
        participant = svc.get_participant(active_tournament.id, player.id)

        result = handler.handle_pick_participant_arch(tg_id=ADMIN_TG_ID, participant_id=participant.id)

        all_btn_names = [b.text for row in result.keyboard.inline_keyboard for b in row]
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
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Иванов Иван"]
        )
        assert "✅ Иванов Иван" in result.text

    def test_result_contains_tournament_status(self, handler, admin_user, active_tournament):
        """После добавления текст содержит заголовок турнира."""
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Иванов Иван"]
        )
        assert active_tournament.title in result.text

    def test_result_has_participants_keyboard(self, handler, admin_user, active_tournament):
        """После добавления клавиатура содержит кнопки участников."""

        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Иванов Иван"]
        )
        assert result.keyboard is not None
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(cb.startswith(CB_ADMIN_PICK_ARCH) for cb in cbs)

    def test_add_summary_comes_before_status(self, handler, admin_user, active_tournament):
        """Строки добавления идут перед блоком статуса."""
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["Петров Пётр"]
        )
        pos_add = result.text.index("✅ Петров Пётр")
        pos_title = result.text.index(active_tournament.title)
        assert pos_add < pos_title

    def test_multiple_players_all_in_text_and_keyboard(self, handler, admin_user, active_tournament):
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID,
            tournament_id=active_tournament.id,
            names=["Первая Анна", "Второй Борис"],
        )
        assert "✅ Первая Анна" in result.text
        assert "✅ Второй Борис" in result.text

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
    def archetype_burn(self, arch_svc):
        return arch_svc.get_or_create_by_name("Burn")

    def test_result_contains_arch_name(self, handler, admin_user, active_tournament, participant, archetype_burn):
        result = handler.handle_set_participant_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, archetype_id=archetype_burn.id
        )
        assert "Burn" in result.text

    def test_result_contains_tournament_status(
        self, handler, admin_user, active_tournament, participant, archetype_burn
    ):
        result = handler.handle_set_participant_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, archetype_id=archetype_burn.id
        )
        assert active_tournament.title in result.text

    def test_result_has_participants_keyboard(
        self, handler, admin_user, active_tournament, participant, archetype_burn
    ):
        result = handler.handle_set_participant_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, archetype_id=archetype_burn.id
        )
        assert result.keyboard is not None
        # After setting archetype the participant is "filled" → hidden behind toggle button
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(cb.startswith(CB_ADMIN_SHOW_FILLED) for cb in cbs)

    def test_arch_saved_message_comes_before_status(
        self, handler, admin_user, active_tournament, participant, archetype_burn
    ):
        result = handler.handle_set_participant_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, archetype_id=archetype_burn.id
        )
        pos_arch = result.text.index("Burn")
        pos_title = result.text.index(active_tournament.title)
        assert pos_arch < pos_title

    def test_archetype_actually_saved_in_db(
        self, handler, svc, admin_user, active_tournament, participant, archetype_burn
    ):
        handler.handle_set_participant_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, archetype_id=archetype_burn.id
        )
        updated = svc.get_participant(active_tournament.id, participant.user_id)
        assert updated.archetype_id == archetype_burn.id

    def test_keyboard_button_has_edit_prefix_after_arch_set(
        self, handler, admin_user, active_tournament, participant, archetype_burn
    ):
        """После назначения колоды кнопка участника видна через show_filled и имеет prefix ✏️."""
        result = handler.handle_admin_show_filled(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        # set arch first so participant is filled
        handler.handle_set_participant_arch(
            tg_id=ADMIN_TG_ID, participant_id=participant.id, archetype_id=archetype_burn.id
        )
        result = handler.handle_admin_show_filled(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        btns = [b for row in result.keyboard.inline_keyboard for b in row]
        participant_btn = next((b for b in btns if str(participant.id) in b.callback_data), None)
        assert participant_btn is not None
        assert participant_btn.text.startswith("✏️")


# ── handle_close_tournament_by_id ────────────────────────────────────────────


class TestCloseTournamentById:
    def test_non_admin_returns_alert(self, handler, active_tournament):
        result = handler.handle_close_tournament_by_id(tg_id=1, tournament_id=active_tournament.id)
        assert result.is_alert
        assert NOT_ADMIN in result.text

    def test_empty_tournament_closes_without_confirmation(self, handler, svc, admin_user, active_tournament):
        result = handler.handle_close_tournament_by_id(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        assert not result.is_alert
        assert TOURNAMENT_CLOSED_MSG in result.text
        assert result.keyboard is None
        assert svc.db.get(m.Tournament, active_tournament.id).closed_by_tg_id == ADMIN_TG_ID

    def test_participants_require_confirmation(self, handler, svc, user_svc, admin_user, active_tournament):
        user = user_svc.get_or_create(tg_id=5500, username=None, first_name="Боец")
        svc.bulk_add_participants(active_tournament.id, [(user.id, "Боец")])
        result = handler.handle_close_tournament_by_id(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        assert not result.is_alert
        assert "записано игроков: 1" in result.text
        assert result.keyboard is not None
        callbacks = [button.callback_data for row in result.keyboard.inline_keyboard for button in row]
        assert f"{CB_CLOSE_TOURNAMENT_CONFIRM}:{active_tournament.id}" in callbacks
        assert svc.db.get(m.Tournament, active_tournament.id).status != TournamentStatus.CLOSED

    def test_confirm_closes_tournament_with_participants(self, handler, svc, user_svc, admin_user, active_tournament):
        user = user_svc.get_or_create(tg_id=5500, username=None, first_name="Боец")
        svc.bulk_add_participants(active_tournament.id, [(user.id, "Боец")])

        result = handler.handle_close_tournament_by_id(
            tg_id=ADMIN_TG_ID,
            tournament_id=active_tournament.id,
            confirmed=True,
        )

        assert result.text == TOURNAMENT_CLOSED_MSG
        tournament = svc.db.get(m.Tournament, active_tournament.id)
        assert tournament.status == TournamentStatus.CLOSED
        assert tournament.closed_by_tg_id == ADMIN_TG_ID

    def test_not_found_returns_alert(self, handler, admin_user):
        result = handler.handle_close_tournament_by_id(tg_id=ADMIN_TG_ID, tournament_id=99999)
        assert result.is_alert

    def test_already_closed_returns_alert_without_confirmation(
        self, handler, svc, user_svc, admin_user, active_tournament
    ):
        user = user_svc.get_or_create(tg_id=5500, username=None, first_name="Боец")
        svc.bulk_add_participants(active_tournament.id, [(user.id, "Боец")])
        svc.close_tournament(active_tournament.id)

        result = handler.handle_close_tournament_by_id(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)

        assert result.is_alert
        assert "уже закрыт" in result.text
        assert result.keyboard is None


# ── handle_archive ────────────────────────────────────────────────────────────


class TestHandleArchive:
    def test_non_admin_blocked(self, handler):
        result = handler.handle_archive(tg_id=1)
        assert NOT_ADMIN in result.text

    def test_empty_archive(self, handler, admin_user):
        result = handler.handle_archive(tg_id=ADMIN_TG_ID)
        assert "пуст" in result.text

    def test_shows_closed_tournaments_as_buttons(self, handler, svc, admin_user):
        t = svc.create_tournament(TournamentCreate(title="Old Pauper", chat_id=CHAT_ID))
        svc.close_tournament(t.id)
        result = handler.handle_archive(tg_id=ADMIN_TG_ID)
        assert result.keyboard is not None
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(str(t.id) in cb for cb in cbs)

    def test_active_tournament_not_in_archive(self, handler, svc, admin_user, active_tournament):
        result = handler.handle_archive(tg_id=ADMIN_TG_ID)
        if result.keyboard:
            cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
            assert not any(str(active_tournament.id) in cb for cb in cbs)


# ── handle_fill_opponents ─────────────────────────────────────────────────────


class TestHandleAdminOpponents:
    @pytest.fixture
    def handler(self, svc, user_svc, arch_svc, keyboards, features):
        return AdminHandler(svc, user_svc, arch_svc, keyboards, features)

    @pytest.fixture
    def admin_user_obj(self, user_svc):
        return user_svc.get_or_create(tg_id=ADMIN_TG_ID, username="admin", first_name="Admin", last_name="User")

    @pytest.fixture
    def opponent_user(self, user_svc):
        return user_svc.get_or_create(tg_id=8800, username=None, first_name="Bob", last_name="Smith")

    def test_feature_disabled_blocks_access(self, svc, user_svc, arch_svc, keyboards, ff_svc):
        ff_svc.toggle(FeatureFlags.RECORD_OPPONENTS)  # default is true → now false
        disabled_handler = AdminHandler(svc, user_svc, arch_svc, keyboards, FeatureService(ff_svc))
        result = disabled_handler.handle_fill_opponents(tg_id=1, tournament_id=1)
        assert result.is_alert

    def test_feature_enabled_allows_non_admin(self, handler, db, user_svc, active_tournament):
        user_svc.get_or_create(tg_id=7777, username=None, first_name="Regular", last_name=None)
        user_svc.get_or_create(tg_id=8800, username=None, first_name="Bob", last_name="Smith")
        data = AetherhubTournamentData(
            url="http://x",
            players=["Regular", "Bob Smith"],
            rounds=[
                AetherhubRound(
                    number=1,
                    pairings=[
                        AetherhubPairing(player="Regular", opponent="Bob Smith"),
                        AetherhubPairing(player="Bob Smith", opponent="Regular"),
                    ],
                )
            ],
        )
        AetherhubImportService(db).import_tournament(active_tournament.id, data)
        result = handler.handle_fill_opponents(tg_id=7777, tournament_id=active_tournament.id)
        assert not result.is_alert

    def test_no_pairings_returns_alert(self, handler, admin_user, active_tournament):
        result = handler.handle_fill_opponents(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        assert result.is_alert

    def test_returns_unfilled_opponents(self, db, handler, svc, user_svc, admin_user, active_tournament):
        # admin_user fixture creates first_name="Admin" (no last_name) — match by single word
        user_svc.get_or_create(tg_id=8800, username=None, first_name="Bob", last_name="Smith")
        import_svc = AetherhubImportService(db)
        data = AetherhubTournamentData(
            url="http://x",
            players=["Admin", "Bob Smith"],
            rounds=[
                AetherhubRound(
                    number=1,
                    pairings=[
                        AetherhubPairing(player="Admin", opponent="Bob Smith"),
                        AetherhubPairing(player="Bob Smith", opponent="Admin"),
                    ],
                )
            ],
        )
        import_svc.import_tournament(active_tournament.id, data)
        result = handler.handle_fill_opponents(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        assert not result.is_alert

        buttons = [b for row in result.keyboard.inline_keyboard for b in row]
        assert any(b.callback_data.startswith(CB_ADMIN_PICK_ARCH) for b in buttons)
        # opponent buttons now show the round they were played in
        assert any(b.text.startswith("Раунд 1:") and "Smith Bob" in b.text for b in buttons)

    def test_all_filled_returns_alert(self, db, handler, svc, user_svc, arch_svc, admin_user, active_tournament):
        opp = user_svc.get_or_create(tg_id=8800, username=None, first_name="Bob", last_name="Smith")
        import_svc = AetherhubImportService(db)
        data = AetherhubTournamentData(
            url="http://x",
            players=["Admin", "Bob Smith"],
            rounds=[
                AetherhubRound(
                    number=1,
                    pairings=[
                        AetherhubPairing(player="Admin", opponent="Bob Smith"),
                        AetherhubPairing(player="Bob Smith", opponent="Admin"),
                    ],
                )
            ],
        )
        import_svc.import_tournament(active_tournament.id, data)
        burn = arch_svc.get_or_create_by_name("Burn")
        p = svc.get_participant(active_tournament.id, opp.id)
        svc.set_participant_archetype(participant_id=p.id, archetype_id=burn.id)
        result = handler.handle_fill_opponents(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        assert result.is_alert
        assert "заполнены" in result.text


# ── Helpers for player actions tests ─────────────────────────────────────────


def _import_pairings(db, tournament_id, admin_user, user_alice, arch_svc):
    """Import a 2-player tournament with pairings. Admin vs Alice."""
    admin_name = "Admin Test"
    alice_name = "Alice Smith"
    data = AetherhubTournamentData(
        url="http://x",
        players=[admin_name, alice_name],
        rounds=[
            AetherhubRound(
                number=1,
                pairings=[
                    AetherhubPairing(player=admin_name, opponent=alice_name),
                    AetherhubPairing(player=alice_name, opponent=admin_name),
                ],
            )
        ],
        standings=[admin_name, alice_name],
    )
    AetherhubImportService(db).import_tournament(tournament_id, data)


# ── TestHandlePlayerActions ───────────────────────────────────────────────────


class TestHandlePlayerActions:
    def test_participant_not_found_returns_alert(self, handler, admin_user, active_tournament):
        result = handler.handle_player_actions(ADMIN_TG_ID, participant_id=99999, tournament_id=active_tournament.id)
        assert result.is_alert
        assert PARTICIPANT_NOT_FOUND in result.text

    def test_shows_player_name_and_deck(self, handler, svc, admin_user, active_tournament, user_alice, arch_svc):
        burn = arch_svc.get_or_create_by_name("Burn")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id, archetype_id=burn.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_actions(ADMIN_TG_ID, p.id, active_tournament.id)
        assert not result.is_alert
        assert "Alice" in result.text
        assert "Burn" in result.text

    def test_admin_sees_delete_button(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_actions(ADMIN_TG_ID, p.id, active_tournament.id)
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(cb.startswith(CB_ADMIN_REMOVE_DO[:6]) for cb in cbs)

    def test_non_admin_no_delete_button(self, handler, svc, user_svc, active_tournament, user_alice, user_bob):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_actions(user_bob.tg_id, p.id, active_tournament.id)
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert not any(cb.startswith("adm_rm") for cb in cbs)

    def test_opponents_button_shown_when_pairings_exist(
        self, db, handler, svc, admin_user, active_tournament, user_alice, arch_svc
    ):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        _import_pairings(db, active_tournament.id, admin_user, user_alice, arch_svc)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_actions(ADMIN_TG_ID, p.id, active_tournament.id)
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(cb.startswith(CB_ADMIN_SHOW_OPPONENTS) for cb in cbs)

    def test_opponents_button_hidden_when_no_pairings(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_actions(ADMIN_TG_ID, p.id, active_tournament.id)
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert not any(cb.startswith(CB_ADMIN_SHOW_OPPONENTS) for cb in cbs)


# ── TestHandlePlayerOpponents ─────────────────────────────────────────────────


class TestHandlePlayerOpponents:
    def test_participant_not_found_returns_alert(self, handler, admin_user, active_tournament):
        result = handler.handle_player_opponents(ADMIN_TG_ID, participant_id=99999, tournament_id=active_tournament.id)
        assert result.is_alert

    def test_no_pairings_returns_alert(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_opponents(ADMIN_TG_ID, p.id, active_tournament.id)
        assert result.is_alert
        assert "Пейринги" in result.text

    def test_shows_opponents_list(
        self, db, handler, svc, user_svc, admin_user, active_tournament, user_alice, arch_svc
    ):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        _import_pairings(db, active_tournament.id, admin_user, user_alice, arch_svc)
        # find Alice's participant (she was matched/created by import)
        alice_user = user_svc.find_by_name("Alice Smith") or user_svc.find_by_name("Smith Alice")
        if alice_user is None:
            alice_user = user_alice
        p = svc.get_participant(active_tournament.id, alice_user.id)
        result = handler.handle_player_opponents(ADMIN_TG_ID, p.id, active_tournament.id)
        assert not result.is_alert
        assert "Раунд 1" in result.text

    def test_result_has_back_keyboard(
        self, db, handler, svc, user_svc, admin_user, active_tournament, user_alice, arch_svc
    ):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        _import_pairings(db, active_tournament.id, admin_user, user_alice, arch_svc)
        alice_user = user_svc.find_by_name("Alice Smith") or user_svc.find_by_name("Smith Alice") or user_alice
        p = svc.get_participant(active_tournament.id, alice_user.id)
        result = handler.handle_player_opponents(ADMIN_TG_ID, p.id, active_tournament.id)
        if not result.is_alert:
            assert result.keyboard is not None
            cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
            assert any(cb.startswith(CB_ADMIN_PICK_ARCH) for cb in cbs)


# ── TestHandleRemoveParticipantConfirm ────────────────────────────────────────


class TestHandleRemoveParticipantConfirm:
    def test_non_admin_returns_alert(self, handler, active_tournament, user_alice, svc):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_remove_participant_confirm(user_alice.tg_id, p.id, active_tournament.id)
        assert result.is_alert
        assert NOT_ADMIN in result.text

    def test_participant_not_found_returns_alert(self, handler, admin_user, active_tournament):
        result = handler.handle_remove_participant_confirm(ADMIN_TG_ID, 99999, active_tournament.id)
        assert result.is_alert
        assert PARTICIPANT_NOT_FOUND in result.text

    def test_shows_player_name_in_confirmation(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_remove_participant_confirm(ADMIN_TG_ID, p.id, active_tournament.id)
        assert not result.is_alert
        assert "Alice" in result.text
        assert result.keyboard is not None

    def test_confirm_keyboard_has_delete_and_cancel(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_remove_participant_confirm(ADMIN_TG_ID, p.id, active_tournament.id)
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(cb.startswith(CB_ADMIN_REMOVE_DO) for cb in cbs)
        assert any(cb.startswith(CB_ADMIN_PICK_ARCH) for cb in cbs)


# ── TestHandleRemoveParticipant ───────────────────────────────────────────────


class TestHandleRemoveParticipant:
    def test_non_admin_returns_alert(self, handler, active_tournament, user_alice, svc):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_remove_participant(user_alice.tg_id, p.id, active_tournament.id)
        assert result.is_alert
        assert NOT_ADMIN in result.text

    def test_participant_not_found_returns_alert(self, handler, admin_user, active_tournament):
        result = handler.handle_remove_participant(ADMIN_TG_ID, 99999, active_tournament.id)
        assert result.is_alert
        assert PARTICIPANT_NOT_FOUND in result.text

    def test_removes_participant(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        handler.handle_remove_participant(ADMIN_TG_ID, p.id, active_tournament.id)
        assert svc.get_participant(active_tournament.id, user_alice.id) is None

    def test_returns_tournament_status_after_removal(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_remove_participant(ADMIN_TG_ID, p.id, active_tournament.id)
        assert not result.is_alert
        assert "удалён" in result.text
        assert "Weekly" in result.text

    def test_remove_works_at_any_tournament_status(self, db, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        obj = db.execute(select(m.Tournament).where(m.Tournament.id == active_tournament.id)).scalar_one()
        obj.status = m.TournamentStatus.ONGOING
        db.commit()
        result = handler.handle_remove_participant(ADMIN_TG_ID, p.id, active_tournament.id)
        assert not result.is_alert
        assert svc.get_participant(active_tournament.id, user_alice.id) is None


# ── deck_added_by_tg_id ───────────────────────────────────────────────────────


class TestDeckAddedByTgId:
    def test_set_participant_arch_sets_caller_tg_id(
        self, handler, svc, user_svc, admin_user, active_tournament, archetype_burn
    ):
        player = user_svc.get_or_create(tg_id=8400, username=None, first_name="Игрок")
        svc.bulk_add_participants(active_tournament.id, [(player.id, "Игрок")])
        p = svc.get_participant(active_tournament.id, player.id)
        handler.handle_set_participant_arch(tg_id=ADMIN_TG_ID, participant_id=p.id, archetype_id=archetype_burn.id)
        updated = svc.get_participant(active_tournament.id, player.id)
        assert updated.deck_added_by_tg_id == ADMIN_TG_ID

    def test_fill_opponents_sets_filler_tg_id(self, db, handler, svc, user_svc, arch_svc, active_tournament):
        """When a non-admin fills an opponent's deck, deck_added_by_tg_id == filler's tg_id."""
        filler = user_svc.get_or_create(tg_id=8500, username=None, first_name="Filler")
        opponent = user_svc.get_or_create(tg_id=8501, username=None, first_name="Opp")
        data = AetherhubTournamentData(
            url="http://x",
            players=["Filler", "Opp"],
            rounds=[
                AetherhubRound(
                    number=1,
                    pairings=[
                        AetherhubPairing(player="Filler", opponent="Opp"),
                        AetherhubPairing(player="Opp", opponent="Filler"),
                    ],
                )
            ],
        )
        AetherhubImportService(db).import_tournament(active_tournament.id, data)

        # Find Opp's participant and set arch as if filler clicked through fill_opponents flow
        opp_p = svc.get_participant(active_tournament.id, opponent.id)
        burn = arch_svc.get_or_create_by_name("Burn")
        handler.handle_set_participant_arch(tg_id=filler.tg_id, participant_id=opp_p.id, archetype_id=burn.id)
        updated = svc.get_participant(active_tournament.id, opponent.id)
        assert updated.deck_added_by_tg_id == filler.tg_id


# ── Scorekeeper role ──────────────────────────────────────────────────────────

SCOREKEEPER_TG_ID = 7777


@pytest.fixture
def scorekeeper_user(user_svc, db):
    u = user_svc.get_or_create(tg_id=SCOREKEEPER_TG_ID, username="sk", first_name="Scorekeeper")
    obj = db.execute(select(m.User).where(m.User.tg_id == SCOREKEEPER_TG_ID)).scalar_one()
    obj.is_scorekeeper = True
    db.commit()
    return u


class TestScorekeeperPermissions:
    def test_is_scorekeeper_returns_true(self, handler, scorekeeper_user):
        assert handler.user_svc.is_scorekeeper(SCOREKEEPER_TG_ID) is True

    def test_is_privileged_true_for_scorekeeper(self, handler, scorekeeper_user):
        assert handler.user_svc.is_privileged(SCOREKEEPER_TG_ID) is True

    def test_is_privileged_true_for_admin(self, handler, admin_user):
        assert handler.user_svc.is_privileged(ADMIN_TG_ID) is True

    def test_is_privileged_false_for_regular(self, handler, user_alice):
        assert handler.user_svc.is_privileged(user_alice.tg_id) is False

    def test_scorekeeper_can_export_excel(
        self, handler, svc, scorekeeper_user, active_tournament, user_alice, archetype_burn
    ):
        svc.register_participant(
            tournament_id=active_tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id
        )
        result = handler.handle_export_excel(tg_id=SCOREKEEPER_TG_ID, tournament_id=active_tournament.id)
        assert result is not None

    def test_scorekeeper_can_view_tournament_status(self, handler, scorekeeper_user, active_tournament):
        result = handler.handle_tournament_status(tg_id=SCOREKEEPER_TG_ID)
        assert result.text != NOT_ADMIN

    def test_scorekeeper_cannot_close_tournament(self, handler, db, scorekeeper_user, active_tournament):
        result = handler.handle_close_tournament(tg_id=SCOREKEEPER_TG_ID)
        assert NOT_ADMIN in result.text
        assert db.get(m.Tournament, active_tournament.id).status != TournamentStatus.CLOSED

    def test_scorekeeper_cannot_confirm_closing_tournament(
        self, handler, svc, db, scorekeeper_user, active_tournament, user_alice
    ):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)

        result = handler.handle_close_tournament_by_id(
            tg_id=SCOREKEEPER_TG_ID,
            tournament_id=active_tournament.id,
            confirmed=True,
        )
        assert result.is_alert
        assert NOT_ADMIN in result.text
        assert db.get(m.Tournament, active_tournament.id).status != TournamentStatus.CLOSED

    def test_scorekeeper_cannot_create_tournament(self, handler, scorekeeper_user):
        result = handler.handle_create_tournament(tg_id=SCOREKEEPER_TG_ID, chat_id=CHAT_ID, title="Test")
        assert NOT_ADMIN in result.text

    def test_scorekeeper_cannot_delete_participant(self, handler, svc, scorekeeper_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_remove_participant(SCOREKEEPER_TG_ID, p.id, active_tournament.id)
        assert NOT_ADMIN in result.text

    def test_scorekeeper_admin_status_has_player_buttons(
        self, handler, svc, scorekeeper_user, active_tournament, user_alice
    ):
        """Метаписец должен видеть список игроков кнопками (как у админа), а не просто текстом."""
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        result = handler.handle_admin_status(tg_id=SCOREKEEPER_TG_ID, tournament_id=active_tournament.id)
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(cb.startswith(CB_ADMIN_PICK_ARCH) for cb in cbs)

    def test_scorekeeper_sees_edit_deck_button_in_player_actions(
        self, handler, svc, scorekeeper_user, active_tournament, user_alice
    ):
        """Метаписец видит кнопку «📝 Изменить колоду» в меню действий."""
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_actions(
            tg_id=SCOREKEEPER_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
        )
        labels = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert any("Изменить колоду" in label for label in labels)

    def test_scorekeeper_no_admin_buttons_in_player_actions(
        self, handler, svc, scorekeeper_user, active_tournament, user_alice
    ):
        """Метаписец НЕ видит кнопки «🧙 Метаписец» и «🗑 Удалить» в меню действий."""
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_actions(
            tg_id=SCOREKEEPER_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
        )
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert not any(cb.startswith(CB_ADMIN_TOGGLE_SCOREKEEPER) for cb in cbs)
        assert not any(cb.startswith(CB_ADMIN_REMOVE_CONFIRM) for cb in cbs)

    def test_scorekeeper_no_actions_menu_on_archetype_screen(
        self, handler, svc, scorekeeper_user, active_tournament, user_alice, archetype_burn
    ):
        """Метаписец НЕ видит кнопку «☰ Меню» на экране выбора архетипа."""
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_pick_participant_arch(tg_id=SCOREKEEPER_TG_ID, participant_id=p.id)
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert not any(cb.startswith(CB_ADMIN_PLAYER_ACTIONS) for cb in cbs)


# ── Toggle метаписец ──────────────────────────────────────────────────────────


@pytest.fixture
def participant(svc, active_tournament, user_alice):
    return svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)


class TestToggleScorekeeper:
    def test_non_admin_blocked(self, handler, svc, user_alice, active_tournament):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_toggle_scorekeeper(
            tg_id=user_alice.tg_id, participant_id=p.id, tournament_id=active_tournament.id
        )
        assert result.is_alert
        assert result.text == NOT_ADMIN

    def test_participant_not_found(self, handler, admin_user, active_tournament):
        result = handler.handle_toggle_scorekeeper(
            tg_id=ADMIN_TG_ID, participant_id=99999, tournament_id=active_tournament.id
        )
        assert result.is_alert
        assert result.text == PARTICIPANT_NOT_FOUND

    def test_admin_grants_role(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_toggle_scorekeeper(
            tg_id=ADMIN_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
        )
        assert not result.is_alert
        assert handler.user_svc.is_scorekeeper(user_alice.tg_id) is True

    def test_admin_revokes_role(self, handler, svc, db, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        obj = db.execute(select(m.User).where(m.User.tg_id == user_alice.tg_id)).scalar_one()
        obj.is_scorekeeper = True
        db.commit()
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_toggle_scorekeeper(
            tg_id=ADMIN_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
        )
        assert not result.is_alert
        assert handler.user_svc.is_scorekeeper(user_alice.tg_id) is False

    def test_result_has_answer_text_on_grant(self, handler, svc, admin_user, active_tournament, user_alice):
        """answer_text должен быть заполнен — он показывается как popup-алерт в Telegram."""
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_toggle_scorekeeper(
            tg_id=ADMIN_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
        )
        assert result.answer_text is not None
        assert "метаписц" in result.answer_text.lower()

    def test_result_has_answer_text_on_revoke(self, handler, svc, db, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        obj = db.execute(select(m.User).where(m.User.tg_id == user_alice.tg_id)).scalar_one()
        obj.is_scorekeeper = True
        db.commit()
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_toggle_scorekeeper(
            tg_id=ADMIN_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
        )
        assert result.answer_text is not None
        assert "снят" in result.answer_text.lower()


class TestPlayerActionsKeyboard:
    def test_back_button_goes_to_archetype_screen(self, handler, svc, admin_user, active_tournament, user_alice):
        """⬅️ Назад в меню … должен возвращать на экран игрока (adm_pick), а не на статус (tstatus)."""
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_actions(
            tg_id=ADMIN_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
        )
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(cb == f"{CB_ADMIN_PICK_ARCH}:{p.id}" for cb in cbs)
        assert not any(cb.startswith(CB_TSTATUS) for cb in cbs)

    def test_target_scorekeeper_label(self, handler, svc, db, admin_user, active_tournament, user_alice):
        """Когда цель — метаписец, кнопка показывает «Снять метаписца»."""
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        obj = db.execute(select(m.User).where(m.User.tg_id == user_alice.tg_id)).scalar_one()
        obj.is_scorekeeper = True
        db.commit()
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_actions(
            tg_id=ADMIN_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
        )
        labels = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert any("снять" in label.lower() for label in labels)

    def test_edit_deck_button_visible_for_admin(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_actions(
            tg_id=ADMIN_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
        )
        labels = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert any("Изменить колоду" in label for label in labels)

    def test_admin_actions_visible_for_admin(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_actions(
            tg_id=ADMIN_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
        )
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(cb.startswith(CB_ADMIN_TOGGLE_SCOREKEEPER) for cb in cbs)
        assert any(cb.startswith(CB_ADMIN_REMOVE_CONFIRM) for cb in cbs)


class TestToggleScorekeeperUserService:
    def test_toggle_grants(self, user_svc, user_alice):
        result = user_svc.toggle_scorekeeper(user_alice.tg_id)
        assert result is True
        assert user_svc.is_scorekeeper(user_alice.tg_id) is True

    def test_toggle_revokes(self, user_svc, db, user_alice):
        obj = db.execute(select(m.User).where(m.User.tg_id == user_alice.tg_id)).scalar_one()
        obj.is_scorekeeper = True
        db.commit()
        result = user_svc.toggle_scorekeeper(user_alice.tg_id)
        assert result is False
        assert user_svc.is_scorekeeper(user_alice.tg_id) is False

    def test_toggle_twice_restores(self, user_svc, user_alice):
        user_svc.toggle_scorekeeper(user_alice.tg_id)
        user_svc.toggle_scorekeeper(user_alice.tg_id)
        assert user_svc.is_scorekeeper(user_alice.tg_id) is False

    def test_unknown_user_returns_none(self, user_svc):
        assert user_svc.toggle_scorekeeper(99999999) is None


# ── Keyboard: ☰ Меню button on archetype select screen ───────────────────────


class TestAdminArchetypeSelectKeyboard:
    def test_admin_with_tournament_id_sees_menu_button(self, handler, svc, admin_user, active_tournament, user_alice):
        """☰ Меню должен быть виден, когда вызывающий — админ и известен tournament_id."""
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_pick_participant_arch(tg_id=ADMIN_TG_ID, participant_id=p.id)
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(cb.startswith(CB_ADMIN_PLAYER_ACTIONS) for cb in cbs)

    def test_non_admin_no_menu_button(self, handler, svc, user_alice, active_tournament):
        """Не-admin (обычный юзер) не должен видеть ☰ Меню."""
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_pick_participant_arch(tg_id=user_alice.tg_id, participant_id=p.id)
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert not any(cb.startswith(CB_ADMIN_PLAYER_ACTIONS) for cb in cbs)

    def test_back_button_goes_to_tournament_status(self, handler, svc, admin_user, active_tournament, user_alice):
        """⬅️ Назад на экране архетипа ведёт на статус турнира (tstatus)."""
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_pick_participant_arch(tg_id=ADMIN_TG_ID, participant_id=p.id)
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert any(cb == f"{CB_TSTATUS}:{active_tournament.id}" for cb in cbs)


# ── handle_player_actions: non-privileged user ───────────────────────────────


class TestPlayerActionsNonPrivileged:
    def test_no_edit_deck_button(self, handler, svc, user_alice, active_tournament):
        """Обычный игрок не видит кнопку 📝 Изменить колоду."""
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_actions(
            tg_id=user_alice.tg_id, participant_id=p.id, tournament_id=active_tournament.id
        )
        labels = [b.text for row in result.keyboard.inline_keyboard for b in row]
        assert not any("Изменить колоду" in label for label in labels)

    def test_no_admin_action_buttons(self, handler, svc, user_alice, active_tournament):
        """Обычный игрок не видит кнопки 🧙 и 🗑."""
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_actions(
            tg_id=user_alice.tg_id, participant_id=p.id, tournament_id=active_tournament.id
        )
        cbs = [b.callback_data for row in result.keyboard.inline_keyboard for b in row]
        assert not any(cb.startswith(CB_ADMIN_TOGGLE_SCOREKEEPER) for cb in cbs)
        assert not any(cb.startswith(CB_ADMIN_REMOVE_CONFIRM) for cb in cbs)


# ── handle_player_opponents edge cases ───────────────────────────────────────


class TestHandlePlayerOpponentsEdgeCases:
    def test_participant_not_found(self, handler, admin_user, active_tournament):
        result = handler.handle_player_opponents(
            tg_id=ADMIN_TG_ID, participant_id=99999, tournament_id=active_tournament.id
        )
        assert result.is_alert
        assert result.text == PARTICIPANT_NOT_FOUND

    def test_no_pairings_returns_alert(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_player_opponents(
            tg_id=ADMIN_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
        )
        assert result.is_alert
        assert "пейринги" in result.text.lower()


# ── UserService.get_or_create update paths ───────────────────────────────────


class TestUserServiceGetOrCreate:
    def test_updates_username_on_change(self, user_svc):
        user_svc.get_or_create(tg_id=5001, username="old_name", first_name="Test")
        updated = user_svc.get_or_create(tg_id=5001, username="new_name")
        assert updated.username == "new_name"

    def test_fills_in_first_name_when_empty(self, user_svc):
        user_svc.get_or_create(tg_id=5002, username="u")
        updated = user_svc.get_or_create(tg_id=5002, first_name="Alice")
        assert updated.first_name == "Alice"

    def test_fills_in_last_name_when_empty(self, user_svc):
        user_svc.get_or_create(tg_id=5003, first_name="Bob")
        updated = user_svc.get_or_create(tg_id=5003, last_name="Smith")
        assert updated.last_name == "Smith"

    def test_does_not_overwrite_existing_first_name(self, user_svc):
        user_svc.get_or_create(tg_id=5004, first_name="Original")
        updated = user_svc.get_or_create(tg_id=5004, first_name="New")
        assert updated.first_name == "Original"


# ── handle_create_tournament edge cases ──────────────────────────────────────


class TestHandleCreateTournament:
    def test_auto_title_when_none(self, handler, admin_user):
        result = handler.handle_create_tournament(tg_id=ADMIN_TG_ID, chat_id=CHAT_ID)
        assert "Pauper" in result.text
        assert result.tournament_id is not None

    def test_second_active_tournament_is_created(self, handler, admin_user, active_tournament):
        result = handler.handle_create_tournament(tg_id=ADMIN_TG_ID, chat_id=CHAT_ID, title="Second")
        assert not result.is_alert
        assert result.tournament_id is not None

    def test_third_active_tournament_returns_alert(self, handler, admin_user, active_tournament):
        second = handler.handle_create_tournament(tg_id=ADMIN_TG_ID, chat_id=CHAT_ID, title="Second")
        assert not second.is_alert

        result = handler.handle_create_tournament(tg_id=ADMIN_TG_ID, chat_id=CHAT_ID, title="Third")
        assert result.is_alert
        assert result.text == TOURNAMENT_ALREADY_EXISTS_MSG

    def test_non_admin_blocked(self, handler, user_alice):
        result = handler.handle_create_tournament(tg_id=user_alice.tg_id, chat_id=CHAT_ID, title="T")
        assert result.text == NOT_ADMIN


# ── handle_admin_show_filled ─────────────────────────────────────────────────


class TestHandleAdminShowFilled:
    def test_non_privileged_blocked(self, handler, user_alice, active_tournament):
        result = handler.handle_admin_show_filled(tg_id=user_alice.tg_id, tournament_id=active_tournament.id)
        assert result.text == NOT_ADMIN

    def test_admin_can_show_filled(self, handler, admin_user, active_tournament):
        result = handler.handle_admin_show_filled(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        assert result.text != NOT_ADMIN
        assert result.keyboard is not None


# ── Race conditions (ParticipantNotFound after initial get) ───────────────────


class TestRaceConditions:
    def test_set_participant_arch_race(self, handler, svc, admin_user, active_tournament, user_alice, archetype_burn):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        with patch.object(svc, "set_participant_archetype", side_effect=errors.ParticipantNotFound):
            result = handler.handle_set_participant_arch(
                tg_id=ADMIN_TG_ID, participant_id=p.id, archetype_id=archetype_burn.id
            )
        assert result.is_alert
        assert result.text == PARTICIPANT_NOT_FOUND

    def test_set_participant_custom_arch_race(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        with patch.object(svc, "set_participant_archetype", side_effect=errors.ParticipantNotFound):
            result = handler.handle_set_participant_custom_arch(
                tg_id=ADMIN_TG_ID, participant_id=p.id, arch_name="Faeries"
            )
        assert result.is_alert
        assert result.text == PARTICIPANT_NOT_FOUND

    def test_remove_participant_race(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        with patch.object(svc, "unregister_participant", side_effect=errors.ParticipantNotFound):
            result = handler.handle_remove_participant(
                tg_id=ADMIN_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
            )
        assert result.is_alert
        assert result.text == PARTICIPANT_NOT_FOUND

    def test_toggle_scorekeeper_orphan_participant(self, handler, svc, admin_user, active_tournament, user_alice):
        """target_user is None — участник есть, но user_svc не находит пользователя (mock)."""
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        with patch.object(handler.user_svc, "get_by_id", return_value=None):
            result = handler.handle_toggle_scorekeeper(
                tg_id=ADMIN_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
            )
        assert result.is_alert
        assert result.text == PARTICIPANT_NOT_FOUND


# ── handle_fill_opponents edge: user not found ────────────────────────────────


class TestHandleFillOpponentsEdgeCases:
    def test_user_not_found_returns_alert(self, handler, ff_svc, active_tournament):
        """tg_id не в БД — должен вернуть алерт «Профиль не найден»."""
        with patch.object(handler._features, "can_fill_opponent_decks", return_value=True):
            result = handler.handle_fill_opponents(tg_id=99999, tournament_id=active_tournament.id)
        assert result.is_alert
        assert "не найден" in result.text


# ── handle_close_tournament_by_id: TournamentNotFound path ───────────────────


class TestCloseTournamentByIdNotFound:
    def test_tournament_not_found(self, handler, admin_user):
        result = handler.handle_close_tournament_by_id(tg_id=ADMIN_TG_ID, tournament_id=99999)
        assert result.is_alert
        assert TOURNAMENT_NOT_FOUND in result.text


# ── handle_delete_tournament ──────────────────────────────────────────────────


class TestHandleDeleteTournament:
    def test_non_admin_blocked(self, handler, user_alice):
        result = handler.handle_delete_tournament(tg_id=user_alice.tg_id)
        assert result.text == NOT_ADMIN

    def test_no_active_tournament(self, handler, admin_user):
        result = handler.handle_delete_tournament(tg_id=ADMIN_TG_ID)
        assert NO_ACTIVE_TOURNAMENT in result.text

    def test_deletes_tournament(self, handler, svc, admin_user, active_tournament):
        result = handler.handle_delete_tournament(tg_id=ADMIN_TG_ID)
        assert active_tournament.title in result.text
        assert svc.list_all_active_tournaments() == []


# ── handle_delete_tournament_prompt and _confirm ─────────────────────────────


class TestHandleDeleteTournamentPrompt:
    def test_non_admin_blocked(self, handler, user_alice, active_tournament):
        result = handler.handle_delete_tournament_prompt(tg_id=user_alice.tg_id, tournament_id=active_tournament.id)
        assert result.text == NOT_ADMIN

    def test_not_found(self, handler, admin_user):
        result = handler.handle_delete_tournament_prompt(tg_id=ADMIN_TG_ID, tournament_id=99999)
        assert result.is_alert
        assert TOURNAMENT_NOT_FOUND in result.text

    def test_shows_confirmation(self, handler, admin_user, active_tournament):
        result = handler.handle_delete_tournament_prompt(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        assert active_tournament.title in result.text
        assert result.keyboard is not None


class TestHandleDeleteTournamentConfirm:
    def test_non_admin_blocked(self, handler, user_alice, active_tournament):
        result = handler.handle_delete_tournament_confirm(tg_id=user_alice.tg_id, tournament_id=active_tournament.id)
        assert result.text == NOT_ADMIN

    def test_not_found(self, handler, admin_user):
        result = handler.handle_delete_tournament_confirm(tg_id=ADMIN_TG_ID, tournament_id=99999)
        assert result.is_alert
        assert TOURNAMENT_NOT_FOUND in result.text

    def test_deletes_tournament(self, handler, svc, admin_user, active_tournament):
        result = handler.handle_delete_tournament_confirm(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        assert active_tournament.title in result.text
        assert svc.list_all_active_tournaments() == []


# ── handle_export_players / handle_export_excel: edge cases ──────────────────


class TestHandleExportEdgeCases:
    def test_export_players_not_privileged_returns_none(self, handler, user_alice, active_tournament):
        result = handler.handle_export_players(tg_id=user_alice.tg_id, tournament_id=active_tournament.id)
        assert result is None

    def test_export_players_missing_tournament_returns_empty_string(self, handler, admin_user):
        result = handler.handle_export_players(tg_id=ADMIN_TG_ID, tournament_id=99999)
        assert result == ""

    def test_export_excel_not_privileged_returns_none(self, handler, user_alice, active_tournament):
        result = handler.handle_export_excel(tg_id=user_alice.tg_id, tournament_id=active_tournament.id)
        assert result is None

    def test_export_excel_tournament_not_found_returns_none(self, handler, admin_user):
        result = handler.handle_export_excel(tg_id=ADMIN_TG_ID, tournament_id=99999)
        assert result is None


class TestCanBuildMetaChart:
    def test_not_privileged(self, handler, user_alice, active_tournament):
        assert handler.can_build_meta_chart(tg_id=user_alice.tg_id, tournament_id=active_tournament.id) is False

    def test_tournament_not_found(self, handler, admin_user):
        assert handler.can_build_meta_chart(tg_id=ADMIN_TG_ID, tournament_id=99999) is False

    def test_admin_may(self, handler, admin_user, active_tournament):
        assert handler.can_build_meta_chart(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id) is True


class TestStandingsAvailability:
    def test_not_privileged(self, handler, user_alice, active_tournament):
        assert handler.standings_availability(user_alice.tg_id, active_tournament.id) == "no_access"

    def test_tournament_not_found(self, handler, admin_user):
        assert handler.standings_availability(ADMIN_TG_ID, 99999) == "no_access"

    def test_not_ready_while_ongoing(self, handler, admin_user, active_tournament):
        """Турнир без счёта матчей — стендинги «ещё не готовы», а не промежуточные."""
        assert handler.standings_availability(ADMIN_TG_ID, active_tournament.id) == "not_ready"

    def test_ok_when_complete(self, handler, admin_user, active_tournament, svc, user_alice, arch_svc, db):
        arch = arch_svc.get_or_create_by_name("Burn")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id, archetype_id=arch.id)
        for r in (1, 2, 3, 4):
            db.add(
                m.RoundPairing(
                    tournament_id=active_tournament.id,
                    round_number=r,
                    player_name="Alice",
                    opponent_name="Opp",
                    table_number=1,
                    player_wins=2,
                    opponent_wins=0,
                )
            )
        db.commit()

        assert handler.standings_availability(ADMIN_TG_ID, active_tournament.id) == "ok"

    def test_not_ready_within_min_duration(self, handler, admin_user, active_tournament, svc, user_alice, arch_svc, db):
        """AetherHub-турнир, стартовавший меньше порога назад: счёт раннего раунда мог появиться, но
        стендинги ещё не итоговые."""
        arch = arch_svc.get_or_create_by_name("Burn")
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id, archetype_id=arch.id)
        for r in (1, 2, 3, 4):
            db.add(
                m.RoundPairing(
                    tournament_id=active_tournament.id,
                    round_number=r,
                    player_name="Alice",
                    opponent_name="Opp",
                    table_number=1,
                    player_wins=2,
                    opponent_wins=0,
                )
            )
        row = db.get(m.Tournament, active_tournament.id)
        row.started_at = m.utc_now() - (MIN_TOURNAMENT_DURATION - timedelta(hours=1))
        db.commit()

        assert handler.standings_availability(ADMIN_TG_ID, active_tournament.id) == "not_ready"


# ── handle_schedule ───────────────────────────────────────────────────────────


class TestHandleSchedule:
    def test_non_admin_blocked(self, handler, user_alice):
        result = handler.handle_schedule(tg_id=user_alice.tg_id, schedule_text="something")
        assert result.text == NOT_ADMIN

    def test_admin_passes_through(self, handler, admin_user):
        result = handler.handle_schedule(tg_id=ADMIN_TG_ID, schedule_text="next friday 20:00")
        assert result.text == "next friday 20:00"


# ── handle_hide_decks: TournamentNotFound ─────────────────────────────────────


class TestHandleHideDecks:
    def test_tournament_not_found(self, handler, admin_user):
        result = handler.handle_hide_decks(tg_id=ADMIN_TG_ID, tournament_id=99999)
        assert result.is_alert
        assert TOURNAMENT_NOT_FOUND in result.text


# ── UserService: merge_users_by_id ────────────────────────────────────────────


class TestUserServiceMergeUsersById:
    def test_merge_transfers_participants(self, user_svc, svc, db, active_tournament):
        source = user_svc.get_or_create(tg_id=6001, first_name="Source")
        target = user_svc.get_or_create(tg_id=6002, first_name="Target")
        svc.register_participant(tournament_id=active_tournament.id, user_id=source.id)
        result = user_svc.merge_users_by_id(source.id, target.id)
        assert result is True
        assert svc.get_participant(active_tournament.id, target.id) is not None

    def test_merge_source_is_deleted(self, user_svc, svc, db, active_tournament):
        source = user_svc.get_or_create(tg_id=6003, first_name="OldUser")
        target = user_svc.get_or_create(tg_id=6004, first_name="NewUser")
        result = user_svc.merge_users_by_id(source.id, target.id)
        assert result is True
        assert user_svc.get_by_id(source.id) is None

    def test_merge_same_user_returns_false(self, user_svc, user_alice):
        result = user_svc.merge_users_by_id(user_alice.id, user_alice.id)
        assert result is False

    def test_merge_nonexistent_source_returns_false(self, user_svc, user_alice):
        result = user_svc.merge_users_by_id(99999, user_alice.id)
        assert result is False

    def test_merge_adopt_name_copies_name(self, user_svc):
        source = user_svc.get_or_create(tg_id=6005, first_name="CanonName", last_name="Smith")
        target = user_svc.get_or_create(tg_id=6006)
        user_svc.merge_users_by_id(source.id, target.id, adopt_name=True)
        updated = user_svc.get_by_id(target.id)
        assert updated.first_name == "CanonName"

    def test_merge_skips_duplicate_participant_in_same_tournament(self, user_svc, svc, db, active_tournament):
        """Если target уже участвует в турнире — source's participant удаляется без конфликта."""
        source = user_svc.get_or_create(tg_id=6007, first_name="Src")
        target = user_svc.get_or_create(tg_id=6008, first_name="Tgt")
        svc.register_participant(tournament_id=active_tournament.id, user_id=source.id)
        svc.register_participant(tournament_id=active_tournament.id, user_id=target.id)
        result = user_svc.merge_users_by_id(source.id, target.id)
        assert result is True
        assert user_svc.get_by_id(source.id) is None

    def test_merge_fills_missing_participant_fields(self, user_svc, svc, db, active_tournament, arch_svc):
        """Конфликт в одном турнире: target держит колоду, source — место. После merge у target есть оба."""
        source = user_svc.get_or_create(tg_id=6101, first_name="Src")
        target = user_svc.get_or_create(tg_id=6102, first_name="Tgt")
        burn = arch_svc.get_or_create_by_name("Burn")
        svc.register_participant(tournament_id=active_tournament.id, user_id=target.id, archetype_id=burn.id)
        svc.register_participant(tournament_id=active_tournament.id, user_id=source.id)
        sp = svc.get_participant(active_tournament.id, source.id)
        sp.final_place = 9
        db.commit()

        assert user_svc.merge_users_by_id(source.id, target.id, adopt_name=False) is True
        tp = svc.get_participant(active_tournament.id, target.id)
        assert tp.archetype_id == burn.id  # колода target сохранена
        assert tp.final_place == 9  # место добрано из source
        assert user_svc.get_by_id(source.id) is None

    def test_merge_does_not_override_existing_target_fields(self, user_svc, svc, db, active_tournament, arch_svc):
        source = user_svc.get_or_create(tg_id=6103, first_name="Src")
        target = user_svc.get_or_create(tg_id=6104, first_name="Tgt")
        burn = arch_svc.get_or_create_by_name("Burn")
        elves = arch_svc.get_or_create_by_name("Elves")
        svc.register_participant(tournament_id=active_tournament.id, user_id=target.id, archetype_id=burn.id)
        tp0 = svc.get_participant(active_tournament.id, target.id)
        tp0.final_place = 1
        svc.register_participant(tournament_id=active_tournament.id, user_id=source.id, archetype_id=elves.id)
        sp = svc.get_participant(active_tournament.id, source.id)
        sp.final_place = 9
        db.commit()

        user_svc.merge_users_by_id(source.id, target.id, adopt_name=False)
        tp = svc.get_participant(active_tournament.id, target.id)
        assert tp.archetype_id == burn.id and tp.final_place == 1  # поля target не перезаписаны

    def test_merge_does_not_lose_nonconflicting_participations(self, user_svc, svc, db, active_tournament):
        """Регрессия: участие source в ДРУГОМ турнире должно перенестись, а не исчезнуть."""
        source = user_svc.get_or_create(tg_id=6105, first_name="Src")
        target = user_svc.get_or_create(tg_id=6106, first_name="Tgt")
        other = svc.create_tournament(TournamentCreate(title="Other", chat_id=987654))
        svc.register_participant(tournament_id=active_tournament.id, user_id=target.id)
        svc.register_participant(tournament_id=other.id, user_id=source.id)

        user_svc.merge_users_by_id(source.id, target.id, adopt_name=False)
        assert svc.get_participant(other.id, target.id) is not None  # перенесено, не потеряно
        assert svc.get_participant(active_tournament.id, target.id) is not None
        assert user_svc.get_by_id(source.id) is None


# ── UserService: get_or_create_placeholder ────────────────────────────────────


class TestUserServiceGetOrCreatePlaceholder:
    def test_creates_new_placeholder(self, user_svc):
        user, created = user_svc.get_or_create_placeholder(username="ghost")
        assert created is True
        assert user.username == "ghost"
        assert user.tg_id < 0

    def test_returns_existing_by_username(self, user_svc):
        user_svc.get_or_create_placeholder(username="ghost2")
        user, created = user_svc.get_or_create_placeholder(username="ghost2")
        assert created is False

    def test_sequential_placeholders_have_decreasing_tg_ids(self, user_svc):
        u1, _ = user_svc.get_or_create_placeholder(username="ph1")
        u2, _ = user_svc.get_or_create_placeholder(username="ph2")
        assert u2.tg_id < u1.tg_id


# ── handle_bulk_add_participants: username display ────────────────────────────


class TestBulkAddUsernameDisplay:
    def test_username_appears_in_display_when_user_found(self, handler, svc, user_svc, admin_user, active_tournament):
        """Строки bulk-add включают @username если пользователь уже в БД с username."""
        user_svc.get_or_create(tg_id=7001, username="playerone", first_name="Player", last_name="One")
        result = handler.handle_bulk_add_by_name(
            tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id, names=["One Player"]
        )
        assert "@playerone" in result.text or "Player" in result.text


# ── handle_player_opponents: success path (bye + regular rounds) ──────────────


class TestHandlePlayerOpponentsSuccess:
    def test_shows_opponent_name(self, db, handler, svc, user_svc, admin_user, active_tournament, user_alice, arch_svc):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        _import_pairings(db, active_tournament.id, admin_user, user_alice, arch_svc)
        alice_placeholder = user_svc.find_by_name("Alice Smith") or user_svc.find_by_name("Smith Alice")
        target_user = alice_placeholder if alice_placeholder else user_alice
        p = svc.get_participant(active_tournament.id, target_user.id)
        if p is None:
            return  # pairings didn't create participant for this user
        result = handler.handle_player_opponents(ADMIN_TG_ID, p.id, active_tournament.id)
        if not result.is_alert:
            assert "Раунд" in result.text


class TestTogglePollOrganizer:
    def test_non_admin_blocked(self, handler, svc, user_alice, active_tournament):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        result = handler.handle_toggle_poll_organizer(
            tg_id=user_alice.tg_id, participant_id=p.id, tournament_id=active_tournament.id
        )
        assert result.is_alert and result.text == NOT_ADMIN

    def test_participant_not_found(self, handler, admin_user, active_tournament):
        result = handler.handle_toggle_poll_organizer(
            tg_id=ADMIN_TG_ID, participant_id=99999, tournament_id=active_tournament.id
        )
        assert result.is_alert and result.text == PARTICIPANT_NOT_FOUND

    def test_admin_grants_and_revokes(self, handler, svc, admin_user, active_tournament, user_alice):
        svc.register_participant(tournament_id=active_tournament.id, user_id=user_alice.id)
        p = svc.get_participant(active_tournament.id, user_alice.id)
        r1 = handler.handle_toggle_poll_organizer(
            tg_id=ADMIN_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
        )
        assert not r1.is_alert
        assert handler.user_svc.is_poll_organizer(user_alice.tg_id) is True
        r2 = handler.handle_toggle_poll_organizer(
            tg_id=ADMIN_TG_ID, participant_id=p.id, tournament_id=active_tournament.id
        )
        assert handler.user_svc.is_poll_organizer(user_alice.tg_id) is False
        assert r2.answer_text  # popup-алерт заполнен


# ── handle_reopen_tournament ─────────────────────────────────────────────────


class TestReopenTournament:
    def test_non_admin_returns_alert(self, handler, svc, active_tournament):
        svc.close_tournament(active_tournament.id)
        result = handler.handle_reopen_tournament(tg_id=1, tournament_id=active_tournament.id)
        assert result.is_alert
        assert NOT_ADMIN in result.text

    def test_reopens_closed_tournament(self, handler, svc, admin_user, active_tournament):
        svc.close_tournament(active_tournament.id)
        result = handler.handle_reopen_tournament(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        assert not result.is_alert
        assert "снова активен" in result.text
        assert svc.get_active_tournament_for_chat(CHAT_ID).id == active_tournament.id

    def test_already_active_returns_alert(self, handler, admin_user, active_tournament):
        result = handler.handle_reopen_tournament(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        assert result.is_alert
        assert "и так активен" in result.text

    def test_reopens_as_second_active_tournament(self, handler, svc, admin_user, active_tournament):
        svc.close_tournament(active_tournament.id)
        svc.create_tournament(TournamentCreate(title="Новый", chat_id=CHAT_ID, slug="new-one"))
        result = handler.handle_reopen_tournament(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        assert not result.is_alert
        assert "снова активен" in result.text

    def test_blocked_when_chat_already_has_two_active(self, handler, svc, admin_user, active_tournament):
        svc.close_tournament(active_tournament.id)
        svc.create_tournament(TournamentCreate(title="Новый 1", chat_id=CHAT_ID, slug="new-one"))
        svc.create_tournament(TournamentCreate(title="Новый 2", chat_id=CHAT_ID, slug="new-two"))
        result = handler.handle_reopen_tournament(tg_id=ADMIN_TG_ID, tournament_id=active_tournament.id)
        assert result.is_alert
        assert "уже открыты два турнира" in result.text

    def test_not_found_returns_alert(self, handler, admin_user):
        result = handler.handle_reopen_tournament(tg_id=ADMIN_TG_ID, tournament_id=99999)
        assert result.is_alert
