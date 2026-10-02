"""Tests for the debug-only internal Swiss simulator."""

import random
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from bot.handlers.debug_swiss import DebugSwissHandler
from bot.keyboards import (
    CB_DEBUG_SWISS_AUTOPLAY,
    CB_DEBUG_SWISS_CLOSE,
    CB_DEBUG_SWISS_CLOSE_ALL_CONFIRM,
    CB_DEBUG_SWISS_CLOSE_CONFIRM,
    CB_DEBUG_SWISS_FILL,
)
from core import models
from core.config import settings
from core.schemas import TournamentCreate
from services import errors
from services.archetype import ArchetypeService
from services.debug_swiss import DEFAULT_PLAYERS, DEFAULT_PLAYOFF_SIZE, DebugSwissService
from services.internal_swiss import InternalSwissService
from services.round_notifications import RoundNotificationService
from services.round_results import FINAL_STATUSES, RoundResultError, RoundResultsService
from services.swiss_requirements_reminders import SwissRequirementsReminderService
from services.tournament import MAX_ACTIVE_TOURNAMENTS_PER_CLUB, TournamentService
from services.user import UserService

NOW = datetime(2026, 9, 18, 15, 45)
# Очевидно фиктивные значения: реальные chat_id живут в config/debug.py.
DEBUG_CHAT = -1009999999999
ADMIN_TG_ID = 999_000_001


@pytest.fixture
def admin(db, user_svc):
    user = user_svc.get_or_create(tg_id=ADMIN_TG_ID, first_name="Админ")
    user.is_admin = True
    db.commit()
    return user


@pytest.fixture
def debug_settings(monkeypatch):
    """Pretend this process is the debug bot talking to the test group only."""
    monkeypatch.setattr("services.debug_swiss.settings.DEBUG", True)
    monkeypatch.setattr("services.debug_swiss.app_cfg.endstep_ru_chat_id", DEBUG_CHAT)
    # settings.chat_ids is a read-only property built from AppConfig.
    monkeypatch.setattr(type(settings), "chat_ids", property(lambda self: [DEBUG_CHAT]))


@pytest.fixture
def service(db, admin, debug_settings):
    return DebugSwissService(db, rng=random.Random(20260918))


def _external_tournament(db) -> models.Tournament:
    """A Swiss tournament in a chat that is not part of the debug allowlist."""
    return TournamentService(db).create_tournament(
        TournamentCreate(
            title="Чужой чат",
            chat_id=-100777,
            is_online=True,
            engine_mode=models.TournamentEngineMode.INTERNAL_SWISS,
            registration_close_at=NOW + timedelta(minutes=15),
        )
    )


# ------------------------------------------------------------------ создание


def test_setup_creates_internal_swiss_in_debug_chat(service, admin):
    tournament = service.create_tournament(players=8, rounds=4, playoff_size=8, admin_tg_id=ADMIN_TG_ID)

    assert tournament.chat_id == DEBUG_CHAT
    assert tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS
    assert tournament.club == "Endstep-ru"
    assert tournament.swiss_large_format is True
    assert tournament.swiss_rounds == 4
    assert tournament.playoff_size == 8
    assert tournament.status == models.TournamentStatus.REGISTRATION
    assert service.planned_rounds_for(4, 8) == 7


def test_setup_uses_documented_defaults(service):
    tournament = service.create_tournament()

    assert tournament.swiss_rounds == 7
    assert tournament.playoff_size == DEFAULT_PLAYOFF_SIZE
    assert "110" in tournament.title


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"players": 1}, "игроков"),
        ({"rounds": 2}, "раундов"),
        ({"playoff_size": 12}, "8 или 16"),
    ],
)
def test_setup_rejects_impossible_settings(service, kwargs, message):
    with pytest.raises(RoundResultError, match=message):
        service.create_tournament(**kwargs)


def test_setup_refuses_foreign_chat_target(service, db):
    _external_tournament(db)

    with pytest.raises(RoundResultError, match="debug-чатов"):
        service.status(_external_tournament(db).id)


def test_close_active_frees_the_club_slot(service, admin):
    created = [
        service.create_tournament(players=8, rounds=3, playoff_size=8) for _ in range(MAX_ACTIVE_TOURNAMENTS_PER_CLUB)
    ]

    with pytest.raises(RoundResultError, match="close-active"):
        service.create_tournament(players=8, rounds=3, playoff_size=8)

    closed = service.close_active_debug_tournaments()

    assert {tournament.id for tournament in closed} == {t.id for t in created}
    next_one = service.create_tournament(players=8, rounds=3, playoff_size=8)
    assert next_one.status == models.TournamentStatus.REGISTRATION


# -------------------------------------------------------------------- поле


def test_fake_players_get_archetype_and_decklist(service, db):
    tournament = service.create_tournament(players=16, rounds=4, playoff_size=8)
    result = service.fill_players(tournament.id, 16)

    assert (result.added, result.total) == (16, 16)
    participants = service._participants(tournament.id)
    assert len(participants) == 16
    for participant in participants:
        assert participant.archetype_id is not None
        assert participant.added_by_admin is True
        assert participant.decklist is not None
        assert participant.decklist.raw_text.strip()
        assert participant.deck_deferred is False


def test_fake_users_never_get_a_real_tg_id(service, db):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)

    users = list(db.execute(select(models.User).where(models.User.username.like("dbg_sw%"))).scalars())

    assert len(users) == 8
    assert {user.tg_id for user in users} == {user.tg_id for user in users if user.tg_id < 0}
    assert all(user.tg_id < 0 for user in users)


def test_fake_usernames_stay_unique_on_refill(service):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)
    second = service.fill_players(tournament.id, 8)

    assert second.added == 0
    usernames = [participant.user.username for participant in service._participants(tournament.id)]
    assert len(set(usernames)) == len(usernames)


def test_fake_players_are_never_reminded_about_decks(service, db):
    """Negative tg_id plus a filled decklist: the reminder query must find nobody."""
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)
    internal = db.get(models.Tournament, tournament.id)
    internal.decklist_reminders_enabled = True
    db.commit()

    pending = SwissRequirementsReminderService(db).pending(internal.registration_close_at - timedelta(minutes=1))

    assert [item.tournament_id for item in pending] == []


def test_fake_players_receive_no_round_notifications(service, db):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)
    InternalSwissService(db, rng=random.Random(7)).generate_next_round(tournament.id, ADMIN_TG_ID)

    notifications = RoundNotificationService(db).build_for_rounds(tournament.id, [1])

    assert notifications == []


def test_fill_is_rejected_after_round_one(service):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)
    service.autoplay_round(tournament.id, ADMIN_TG_ID)

    with pytest.raises(RoundResultError, match="до первого раунда"):
        service.fill_players(tournament.id, 16)


# ----------------------------------------------------------------- автоплей


def test_autoplay_uses_the_real_engine(service, db, admin):
    tournament = service.create_tournament(players=16, rounds=4, playoff_size=8)
    service.fill_players(tournament.id, 16)

    step = service.autoplay_round(tournament.id, ADMIN_TG_ID)

    assert step.round_number == 1
    assert step.planned_rounds == 7
    assert step.matches == 8
    assert db.get(models.Tournament, tournament.id).status == models.TournamentStatus.ONGOING
    # The real engine pairs by exact user ids, so every match resolves to a fake user.
    for match in RoundResultsService(db).list_round(tournament.id, 1):
        assert match.player1_user_id is not None
        assert match.player2_user_id is not None


def test_autoplay_scores_previous_round_before_generating_next(service, db):
    tournament = service.create_tournament(players=8, rounds=4, playoff_size=8)
    service.fill_players(tournament.id, 8)
    service.autoplay_round(tournament.id, ADMIN_TG_ID)

    second = service.autoplay_round(tournament.id, ADMIN_TG_ID)

    assert second.round_number == 2
    assert second.completed_previous == 4
    for match in RoundResultsService(db).list_round(tournament.id, 1):
        assert match.status in FINAL_STATUSES


def test_autoplay_refuses_a_non_admin_actor(service, db, user_svc):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)
    stranger = user_svc.get_or_create(tg_id=424242, first_name="Посторонний")

    with pytest.raises(RoundResultError, match="прав"):
        service.autoplay_round(tournament.id, stranger.tg_id)


def test_autoplay_runs_a_110_player_field_through_every_planned_round(service, db):
    """The headline case: 110 players, 7 Swiss rounds and a top-8 playoff."""
    tournament = service.create_tournament(players=DEFAULT_PLAYERS, rounds=7, playoff_size=8)
    service.fill_players(tournament.id, DEFAULT_PLAYERS)

    run = service.autoplay_all(tournament.id, ADMIN_TG_ID)

    assert run.completed is True
    assert run.planned == 10
    assert run.played == 10
    assert [step.round_number for step in run.rounds] == list(range(1, 11))
    # Even field: no byes, exactly half the players per round.
    assert run.rounds[0].matches == DEFAULT_PLAYERS // 2
    # Playoff shrinks the field to the cut.
    assert run.rounds[7].matches == 4


def test_full_110_player_run_ends_closed_with_unique_places(service, db):
    """End-to-end default config: fill → play every round → finish, nothing real touched."""
    tournament = service.create_tournament(players=DEFAULT_PLAYERS, rounds=7, playoff_size=8)
    service.fill_players(tournament.id, DEFAULT_PLAYERS)
    service.autoplay_all(tournament.id, ADMIN_TG_ID)

    standings = service.finish(tournament.id, ADMIN_TG_ID)

    assert len(standings) == DEFAULT_PLAYERS
    assert sorted(row.place for row in standings) == list(range(1, DEFAULT_PLAYERS + 1))
    participants = service._participants(tournament.id)
    assert all(row.final_place for row in participants)
    assert db.get(models.Tournament, tournament.id).status == models.TournamentStatus.CLOSED
    # The whole field is fake: unique negative ids, arch + decklist, never notified.
    users = list(db.execute(select(models.User).where(models.User.username.like("dbg_sw%"))).scalars())
    assert len({user.tg_id for user in users}) == DEFAULT_PLAYERS
    assert all(user.tg_id < 0 for user in users)
    assert all(row.decklist is not None and row.decklist.raw_text.strip() for row in participants)
    assert RoundNotificationService(db).build_for_rounds(tournament.id, list(range(1, 11))) == []


def test_playoff_matches_never_end_in_a_draw(service, db):
    tournament = service.create_tournament(players=16, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 16)
    run = service.autoplay_all(tournament.id, ADMIN_TG_ID)
    assert run.completed is True

    results = RoundResultsService(db)
    scored_playoff = 0
    for round_number in range(4, 7):
        for match in results.list_round(tournament.id, round_number):
            if match.status not in FINAL_STATUSES:
                continue
            scored_playoff += 1
            assert match.player1_wins != match.player2_wins
    assert scored_playoff > 0
    # The last round is scored too, so finish() is a separate explicit step that will work.
    assert all(match.status in FINAL_STATUSES for match in results.list_round(tournament.id, 6))


def test_finish_requires_every_planned_round(service):
    tournament = service.create_tournament(players=8, rounds=4, playoff_size=8)
    service.fill_players(tournament.id, 8)
    service.autoplay_round(tournament.id, ADMIN_TG_ID)

    with pytest.raises(RoundResultError, match="раунд"):
        service.finish(tournament.id, ADMIN_TG_ID)


def test_finish_assigns_places_and_closes_the_tournament(service, db):
    tournament = service.create_tournament(players=16, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 16)
    service.autoplay_all(tournament.id, ADMIN_TG_ID)

    standings = service.finish(tournament.id, ADMIN_TG_ID)

    assert standings[0].place == 1
    assert standings[0].match_points == 9
    closed = db.get(models.Tournament, tournament.id)
    assert closed.status == models.TournamentStatus.CLOSED
    places = {p.final_place for p in service._participants(tournament.id)}
    assert places == set(range(1, 17))


def test_status_reports_progress_and_readiness(service):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)

    before = service.status(tournament.id)
    service.autoplay_round(tournament.id, ADMIN_TG_ID)
    after = service.status(tournament.id)

    assert (before.round_number, before.can_autoplay) == (0, True)
    assert (after.round_number, after.can_autoplay) == (1, True)
    assert after.round_number < after.planned_rounds
    assert after.scores_collected is False
    assert after.active_players == 8


def test_status_reports_nothing_to_do_after_the_last_round(service):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)
    run = service.autoplay_all(tournament.id, ADMIN_TG_ID)

    final = service.status(tournament.id)

    assert (final.round_number, final.planned_rounds) == (run.planned, run.planned)
    assert final.scores_collected is True
    assert final.can_autoplay is False


def test_autoplay_all_keeps_tournament_open_for_manual_finish(service, db):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)
    service.autoplay_all(tournament.id, ADMIN_TG_ID)

    assert db.get(models.Tournament, tournament.id).status == models.TournamentStatus.ONGOING


def test_tournament_from_another_chat_cannot_be_simulated(service, db):
    external = _external_tournament(db)

    with pytest.raises(RoundResultError, match="debug-чатов"):
        service.autoplay_round(external.id, ADMIN_TG_ID)


def test_simulator_refuses_to_run_in_production(db, admin, monkeypatch):
    monkeypatch.setattr("services.debug_swiss.settings.DEBUG", False)
    service = DebugSwissService(db, rng=random.Random(1))

    with pytest.raises(RoundResultError, match="BOT_ENV=debug"):
        service.create_tournament(players=8, rounds=3, playoff_size=8)


# ----------------------------------------------------------------- handlers


def test_handler_panel_is_blocked_outside_debug(db, service, admin, monkeypatch):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)
    monkeypatch.setattr("bot.handlers.debug_swiss.settings.DEBUG", False)

    result = DebugSwissHandler(db).handle_panel(tournament.id, ADMIN_TG_ID)

    assert result.is_alert is True
    assert "debug" in result.text


def test_handler_panel_shows_field_and_progress(db, service, admin):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)

    result = DebugSwissHandler(db).handle_panel(tournament.id, ADMIN_TG_ID)

    assert result.is_alert is False
    assert "Раундов: 0/6" in result.text
    assert "отрицательный tg_id" in result.text
    labels = [button.text for row in result.keyboard.inline_keyboard for button in row]
    assert "👥 Игроки ×110" in labels
    assert "▶️ Раунд +1" in labels
    assert "⏩ До конца" in labels


def test_handler_fill_tops_up_the_field(db, service, admin):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)

    result = DebugSwissHandler(db).handle_fill(tournament.id, ADMIN_TG_ID, 16)

    assert result.is_alert is False
    assert result.answer_text == "Добавлено 8. Всего игроков: 16."


def test_handler_autoplay_returns_the_real_round_screen(db, service, admin):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)

    result = DebugSwissHandler(db).handle_autoplay(tournament.id, ADMIN_TG_ID)

    assert result.is_alert is False
    assert "Раунд 1" in result.text
    assert result.answer_text is not None and "Раунд 1/6" in result.answer_text


def test_handler_run_all_plays_everything(db, service, admin):
    tournament = service.create_tournament(players=16, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 16)

    result = DebugSwissHandler(db).handle_run_all(tournament.id, ADMIN_TG_ID)

    assert result.is_alert is False
    assert "Сыграно и засчитано раундов: 6/6." in result.answer_text


def test_handler_rejects_a_non_swiss_tournament(db, service, admin):
    aetherhub = TournamentService(db).create_tournament(
        TournamentCreate(title="AetherHub", chat_id=DEBUG_CHAT, is_online=True)
    )

    result = DebugSwissHandler(db).handle_panel(aetherhub.id, ADMIN_TG_ID)

    assert result.is_alert is True
    assert "внутреннего Swiss" in result.text


def test_archetype_pool_falls_back_to_seed(db, service):
    assert ArchetypeService(db).list_top_archetypes(n=5) == []
    tournament = service.create_tournament(players=4, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 4)

    assert len(ArchetypeService(db).list_top_archetypes(n=20)) >= 4


def test_external_tournament_registration_still_rejects_missing_archetype(db):
    with pytest.raises(errors.ParticipantError):
        TournamentService(db).register_participant(
            tournament_id=_external_tournament(db).id,
            user_id=UserService(db).get_or_create(tg_id=5150, first_name="X").id,
        )


# --------------------------------------------------------------- forced close


def test_force_close_works_before_the_first_round(service, db):
    tournament = service.create_tournament(players=16, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 16)

    closed = service.force_close(tournament.id, ADMIN_TG_ID)

    assert closed.status == models.TournamentStatus.CLOSED
    assert closed.closed_by_tg_id == ADMIN_TG_ID
    assert db.get(models.Tournament, tournament.id).status == models.TournamentStatus.CLOSED


def test_force_close_works_with_rounds_left_unplayed(service, db):
    tournament = service.create_tournament(players=16, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 16)
    service.autoplay_round(tournament.id, ADMIN_TG_ID)

    with pytest.raises(RoundResultError, match="Сначала"):
        InternalSwissService(db).finish(tournament.id, ADMIN_TG_ID)

    closed = service.force_close(tournament.id, ADMIN_TG_ID)

    assert closed.status == models.TournamentStatus.CLOSED
    assert closed.ended_at is not None
    # Places stay empty: an unfinished Swiss must not invent rankings.
    assert all(participant.final_place is None for participant in service._participants(tournament.id))


def test_force_close_refuses_a_foreign_chat(service, db):
    external = _external_tournament(db)

    with pytest.raises(RoundResultError, match="debug-чатов"):
        service.force_close(external.id, ADMIN_TG_ID)

    assert db.get(models.Tournament, external.id).status == models.TournamentStatus.REGISTRATION


def test_force_close_refuses_a_stranger(service, db, user_svc):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    stranger = user_svc.get_or_create(tg_id=777_777, first_name="Чужой")
    db.commit()

    with pytest.raises(RoundResultError, match="прав"):
        service.force_close(tournament.id, stranger.tg_id)

    assert db.get(models.Tournament, tournament.id).status == models.TournamentStatus.REGISTRATION


def test_force_close_twice_is_a_no_op_error(service):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.force_close(tournament.id, ADMIN_TG_ID)

    with pytest.raises(RoundResultError, match="уже закрыт"):
        service.force_close(tournament.id, ADMIN_TG_ID)


def test_force_close_active_frees_all_club_slots(service, db):
    for _ in range(MAX_ACTIVE_TOURNAMENTS_PER_CLUB):
        service.create_tournament(players=8, rounds=3, playoff_size=8)

    with pytest.raises(RoundResultError, match=f"{MAX_ACTIVE_TOURNAMENTS_PER_CLUB} активных"):
        service.create_tournament(players=8, rounds=3, playoff_size=8)

    closed = service.force_close_active(ADMIN_TG_ID)

    assert len(closed) == MAX_ACTIVE_TOURNAMENTS_PER_CLUB
    assert all(row.status == models.TournamentStatus.CLOSED for row in closed)
    assert service.active_club_tournaments() == []
    # A fresh setup fits again.
    assert service.create_tournament(players=8, rounds=3, playoff_size=8).status == models.TournamentStatus.REGISTRATION


def test_force_close_active_refuses_a_stranger(service, db, user_svc):
    service.create_tournament(players=8, rounds=3, playoff_size=8)
    stranger = user_svc.get_or_create(tg_id=777_777, first_name="Чужой")
    db.commit()

    with pytest.raises(RoundResultError, match="прав"):
        service.force_close_active(stranger.tg_id)

    assert len(service.active_club_tournaments()) == 1


def test_force_close_is_refused_in_production(db, admin, monkeypatch):
    monkeypatch.setattr("services.debug_swiss.settings.DEBUG", False)
    service = DebugSwissService(db, rng=random.Random(1))

    with pytest.raises(RoundResultError, match="BOT_ENV=debug"):
        service.force_close_active(ADMIN_TG_ID)


def test_handler_close_prompt_warns_and_offers_confirmation(db, service, admin):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)

    result = DebugSwissHandler(db).handle_close_prompt(tournament.id, ADMIN_TG_ID)

    assert result.is_alert is False
    assert "0/6" in result.text
    assert "места не расставляются" in result.text
    callbacks = {button.callback_data for row in result.keyboard.inline_keyboard for button in row}
    assert f"{CB_DEBUG_SWISS_CLOSE_CONFIRM}:{tournament.id}" in callbacks
    # Nothing is closed until the admin presses the confirmation button.
    assert db.get(models.Tournament, tournament.id).status == models.TournamentStatus.REGISTRATION


def test_handler_force_close_closes_and_returns_to_the_panel(db, service, admin):
    tournament = service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.fill_players(tournament.id, 8)

    result = DebugSwissHandler(db).handle_force_close(tournament.id, ADMIN_TG_ID)

    assert db.get(models.Tournament, tournament.id).status == models.TournamentStatus.CLOSED
    assert result.answer_text == f"Закрыт турнир #{tournament.id}."
    callbacks = {button.callback_data for row in result.keyboard.inline_keyboard for button in row}
    # A closed tournament offers no fill or autoplay buttons any more.
    assert f"{CB_DEBUG_SWISS_FILL}:{tournament.id}:16" not in callbacks
    assert f"{CB_DEBUG_SWISS_AUTOPLAY}:{tournament.id}" not in callbacks
    assert f"{CB_DEBUG_SWISS_CLOSE}:{tournament.id}" in callbacks


def test_handler_close_all_prompt_lists_open_tournaments(db, service, admin):
    first = service.create_tournament(players=8, rounds=3, playoff_size=8)
    second = service.create_tournament(players=8, rounds=3, playoff_size=8)

    result = DebugSwissHandler(db).handle_close_all_prompt(first.id, ADMIN_TG_ID)

    assert "Открытых турниров клуба: 2" in result.text
    assert f"#{first.id}" in result.text and f"#{second.id}" in result.text
    callbacks = {button.callback_data for row in result.keyboard.inline_keyboard for button in row}
    assert f"{CB_DEBUG_SWISS_CLOSE_ALL_CONFIRM}:{first.id}" in callbacks
    assert len(service.active_club_tournaments()) == 2


def test_handler_force_close_all_frees_the_club(db, service, admin):
    service.create_tournament(players=8, rounds=3, playoff_size=8)
    service.create_tournament(players=8, rounds=3, playoff_size=8)

    result = DebugSwissHandler(db).handle_force_close_all(1, ADMIN_TG_ID)

    assert result.answer_text == "Закрыто турниров: 2. Слоты клуба свободны."
    assert service.active_club_tournaments() == []
