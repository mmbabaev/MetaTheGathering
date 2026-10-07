"""Handler-level coverage for bot/handlers/round_results.py: error paths and admin flows."""

from __future__ import annotations

import random
from datetime import datetime

import pytest

from bot.handlers.round_results import RoundResultsHandler
from core import models
from core.schemas import TournamentCreate
from services.internal_swiss import InternalSwissService
from services.round_results import RoundResultsService
from services.tournament import TournamentService
from services.user import UserService


def _internal_setup(db, count: int = 4):
    tournament = TournamentService(db).create_tournament(
        TournamentCreate(
            title="Internal",
            chat_id=-1001,
            club="Endstep-ru",
            is_online=True,
            registration_close_at=datetime(2026, 9, 20, 16, 0),
        )
    )
    archetype = models.Archetype(name="Test Archetype")
    db.add(archetype)
    db.flush()
    users = []
    for index in range(count):
        user = UserService(db).get_or_create(
            tg_id=1000 + index,
            username=f"player{index}",
            first_name=f"Имя{index}",
            last_name=f"Фамилия{index}",
        )
        db.add(models.Participant(tournament_id=tournament.id, user_id=user.id, archetype_id=archetype.id))
        users.append(user)
    admin = users[0]
    admin.is_admin = True
    db.commit()
    engine = InternalSwissService(db, rng=random.Random(7))
    engine.set_enabled(tournament.id, admin.tg_id, True)
    return tournament, users, admin, engine


def _draft_setup(db, tg: int = 7001):
    organizer = UserService(db).get_or_create(tg_id=tg, username="draft_owner", first_name="Owner")
    organizer.is_tournament_organizer = True
    tournament = TournamentService(db).create_tournament(
        TournamentCreate(
            title="Endstep draft",
            chat_id=-1003964019099,
            club="Endstep draft",
            is_online=True,
            is_draft=True,
            engine_mode=models.TournamentEngineMode.INTERNAL_SWISS,
            registration_close_at=datetime(2026, 9, 20, 16, 0),
            created_by_tg_id=organizer.tg_id,
            decklist_reminders_enabled=False,
        )
    )
    users = []
    for index in range(8):
        user = UserService(db).get_or_create(
            tg_id=tg + 100 + index,
            username=f"drafter{index}",
            first_name=f"Игрок{index}",
        )
        db.add(models.Participant(tournament_id=tournament.id, user_id=user.id))
        users.append(user)
    db.commit()
    engine = InternalSwissService(db, rng=random.Random(11))
    return tournament, users, organizer, engine


def _aetherhub_match(db):
    tournament = TournamentService(db).create_tournament(
        TournamentCreate(title="Endstep Test", chat_id=100, is_online=True)
    )
    users = []
    for index, (first, last) in enumerate([("Алиса", "Иванова"), ("Борис", "Петров"), ("Вера", "Сидорова")]):
        user = UserService(db).get_or_create(
            tg_id=101 + index,
            username=f"user{index}",
            first_name=first,
            last_name=last,
        )
        db.add(models.Participant(tournament_id=tournament.id, user_id=user.id))
        users.append(user)
    alice, bob, carol = users
    db.add_all(
        [
            models.RoundPairing(
                tournament_id=tournament.id,
                round_number=1,
                table_number=1,
                player_name="Иванова Алиса",
                opponent_name="Петров Борис",
            ),
            models.RoundPairing(
                tournament_id=tournament.id,
                round_number=1,
                table_number=1,
                player_name="Петров Борис",
                opponent_name="Иванова Алиса",
            ),
        ]
    )
    db.commit()
    match = RoundResultsService(db).sync_round(tournament.id, 1)[0]
    return tournament, alice, bob, carol, match


# --- handle_round_status guards ---


def test_round_status_unknown_tournament(db):
    result = RoundResultsHandler(db).handle_round_status(9999, tg_id=1)
    assert result.is_alert
    assert result.text == "Турнир не найден."


def test_round_status_without_pairings(db):
    tournament = TournamentService(db).create_tournament(TournamentCreate(title="Empty", chat_id=100, is_online=True))
    result = RoundResultsHandler(db).handle_round_status(tournament.id, tg_id=None)
    assert result.is_alert
    assert result.text == "Паринги ещё не загружены."


# --- player score flow guards ---


def test_open_unknown_user(db):
    _, _, _, _, match = _aetherhub_match(db)
    result = RoundResultsHandler(db).handle_open(match.tournament_id, tg_id=999999)
    assert not result.is_alert
    assert "не зарегистрированы" in result.text


def test_own_wins_unknown_user(db):
    _, _, _, _, match = _aetherhub_match(db)
    result = RoundResultsHandler(db).handle_own_wins(match.id, tg_id=999999, own_wins=1)
    assert result.is_alert
    assert "не найден" in result.text


def test_own_wins_match_of_another_player(db):
    _, _, _, carol, match = _aetherhub_match(db)
    result = RoundResultsHandler(db).handle_own_wins(match.id, tg_id=carol.tg_id, own_wins=1)
    assert result.is_alert
    assert "не принадлежит" in result.text


def test_opponent_wins_flow_and_guard(db):
    _, alice, _, carol, match = _aetherhub_match(db)
    handler = RoundResultsHandler(db)
    result = handler.handle_opponent_wins(match.id, alice.tg_id, own_wins=2, opponent_wins=0)
    assert not result.is_alert
    assert "Передать сопернику на подтверждение?" in result.text
    guarded = handler.handle_opponent_wins(match.id, carol.tg_id, own_wins=2, opponent_wins=0)
    assert guarded.is_alert
    assert "не принадлежит" in guarded.text


def test_send_invalid_score_is_alert(db):
    _, alice, _, _, match = _aetherhub_match(db)
    result = RoundResultsHandler(db).handle_send(match.id, alice.tg_id, own_wins=2, opponent_wins=2)
    assert result.screen.is_alert


def test_confirm_stale_revision_is_alert(db):
    _, alice, bob, _, match = _aetherhub_match(db)
    handler = RoundResultsHandler(db)
    handler.handle_send(match.id, alice.tg_id, own_wins=2, opponent_wins=1)
    result = handler.handle_confirm(match.id, revision=9999, tg_id=bob.tg_id)
    assert result.screen.is_alert


def test_reject_flow_delivers_to_proposer(db):
    _, alice, bob, _, match = _aetherhub_match(db)
    handler = RoundResultsHandler(db)
    handler.handle_send(match.id, bob.tg_id, own_wins=1, opponent_wins=2)
    stored = RoundResultsService(db).get_match(match.id)
    result = handler.handle_reject(match.id, stored.revision, alice.tg_id)
    assert not result.screen.is_alert
    assert "Результат отклонён" in result.screen.text
    assert result.recipient_tg_id == bob.tg_id
    assert result.recipient_text is not None


def test_reject_by_non_player_is_alert(db):
    _, alice, bob, carol, match = _aetherhub_match(db)
    handler = RoundResultsHandler(db)
    handler.handle_send(match.id, bob.tg_id, own_wins=1, opponent_wins=2)
    stored = RoundResultsService(db).get_match(match.id)
    result = handler.handle_reject(match.id, stored.revision, carol.tg_id)
    assert result.screen.is_alert


# --- admin flows ---


def test_admin_list_requires_rights_and_pairings(db):
    tournament, users, admin, _ = _internal_setup(db)
    carol_tg = 5001
    UserService(db).get_or_create(tg_id=carol_tg, username="carol", first_name="Carol")
    handler = RoundResultsHandler(db)
    denied = handler.handle_admin_list(tournament.id, carol_tg)
    assert denied.is_alert
    assert denied.text == "Нет прав организатора."
    empty = handler.handle_admin_list(tournament.id, admin.tg_id)
    assert empty.is_alert
    assert empty.text == "Паринги ещё не загружены."


def test_admin_match_requires_rights_and_unknown_match(db):
    _, _, _, _, match = _aetherhub_match(db)
    carol_tg = 5001
    UserService(db).get_or_create(tg_id=carol_tg, username="carol", first_name="Carol")
    handler = RoundResultsHandler(db)
    denied = handler.handle_admin_match(match.id, carol_tg)
    assert denied.is_alert
    assert denied.text == "Нет прав организатора."
    alice = UserService(db).get_by_tg_id(101)
    alice.is_admin = True
    db.commit()
    missing = handler.handle_admin_match(9999, alice.tg_id)
    assert missing.is_alert


def test_admin_p1_requires_rights(db):
    _, _, _, _, match = _aetherhub_match(db)
    carol_tg = 5001
    UserService(db).get_or_create(tg_id=carol_tg, username="carol", first_name="Carol")
    result = RoundResultsHandler(db).handle_admin_p1(match.id, carol_tg, player1_wins=2)
    assert result.is_alert
    assert result.text == "Нет прав организатора."


def test_admin_p1_unknown_match_is_alert(db):
    _, alice, _, _, _ = _aetherhub_match(db)
    alice.is_admin = True
    db.commit()
    result = RoundResultsHandler(db).handle_admin_p1(9999, alice.tg_id, player1_wins=2)
    assert result.is_alert


def test_admin_p2_invalid_score_is_alert(db):
    _, alice, _, _, match = _aetherhub_match(db)
    alice.is_admin = True
    db.commit()
    result = RoundResultsHandler(db).handle_admin_p2(match.id, alice.tg_id, player1_wins=2, player2_wins=2)
    assert result.is_alert


def test_summary_requires_rights_and_renders(db):
    tournament, alice, _, _, match = _aetherhub_match(db)
    carol_tg = 5001
    UserService(db).get_or_create(tg_id=carol_tg, username="carol", first_name="Carol")
    handler = RoundResultsHandler(db)
    denied = handler.handle_summary(tournament.id, carol_tg)
    assert denied.is_alert
    assert denied.text == "Нет прав организатора."
    alice.is_admin = True
    db.commit()
    rendered = handler.handle_summary(tournament.id, alice.tg_id)
    assert not rendered.is_alert
    assert rendered.keyboard is not None


def test_summary_without_pairings(db):
    tournament, users, admin, _ = _internal_setup(db)
    result = RoundResultsHandler(db).handle_summary(tournament.id, admin.tg_id)
    assert result.is_alert
    assert result.text == "Паринги ещё не загружены."


def test_toggle_view_requires_rights(db):
    tournament, *_ = _internal_setup(db)
    carol_tg = 5001
    UserService(db).get_or_create(tg_id=carol_tg, username="carol", first_name="Carol")
    result = RoundResultsHandler(db).handle_toggle_view(tournament.id, carol_tg)
    assert result.is_alert


# --- internal swiss engine switches ---


def test_swiss_toggle_unknown_tournament(db):
    _, _, admin, _ = _internal_setup(db)
    result = RoundResultsHandler(db).handle_swiss_toggle(9999, admin.tg_id)
    assert result.is_alert
    assert result.text == "Турнир не найден."


def test_swiss_toggle_requires_rights(db):
    tournament, users, admin, _ = _internal_setup(db)
    denied = RoundResultsHandler(db).handle_swiss_toggle(tournament.id, users[1].tg_id)
    assert denied.is_alert


def test_swiss_next_round_requires_rights(db):
    tournament, users, admin, _ = _internal_setup(db)
    denied = RoundResultsHandler(db).handle_swiss_next_round(tournament.id, users[1].tg_id)
    assert denied.is_alert


def test_draft_seating_requires_rights_and_renders(db):
    tournament, users, organizer, engine = _draft_setup(db)
    stranger_tg = 9001
    UserService(db).get_or_create(tg_id=stranger_tg, username="stranger", first_name="Stranger")
    handler = RoundResultsHandler(db)
    denied = handler.handle_draft_seating(tournament.id, stranger_tg)
    assert denied.is_alert
    seated = handler.handle_draft_seating(tournament.id, organizer.tg_id)
    assert not seated.is_alert
    assert "🪑 Рассадка игроков" in seated.text
    assert "1. " in seated.text
    assert "8. " in seated.text


# --- standings ---


def test_swiss_standings_guards(db):
    tournament, *_ = _internal_setup(db)
    handler = RoundResultsHandler(db)
    missing = handler.handle_swiss_standings(9999, tg_id=1)
    assert missing.is_alert
    assert missing.text == "Турнир не найден."
    aetherhub = TournamentService(db).create_tournament(TournamentCreate(title="AH", chat_id=100, is_online=True))
    wrong_engine = handler.handle_swiss_standings(aetherhub.id, tg_id=1)
    assert wrong_engine.is_alert
    assert "AetherHub" in wrong_engine.text


def test_swiss_standings_pagination_clamps(db):
    tournament, users, admin, engine = _internal_setup(db, count=25)
    engine.generate_next_round(tournament.id, admin.tg_id)
    handler = RoundResultsHandler(db)
    first = handler.handle_swiss_standings(tournament.id, admin.tg_id, page=0)
    last = handler.handle_swiss_standings(tournament.id, admin.tg_id, page=1)
    overflow = handler.handle_swiss_standings(tournament.id, admin.tg_id, page=99)
    assert not first.is_alert and not last.is_alert and not overflow.is_alert
    assert first.text != last.text
    assert overflow.text == last.text


# --- finish ---


def test_finish_prompt_guards(db):
    tournament, users, admin, engine = _internal_setup(db)
    handler = RoundResultsHandler(db)
    missing = handler.handle_swiss_finish_prompt(9999, admin.tg_id)
    assert missing.is_alert
    assert missing.text == "Внутренний Swiss-турнир не найден."
    aetherhub = TournamentService(db).create_tournament(TournamentCreate(title="AH", chat_id=100, is_online=True))
    wrong_engine = handler.handle_swiss_finish_prompt(aetherhub.id, admin.tg_id)
    assert wrong_engine.is_alert
    too_early = handler.handle_swiss_finish_prompt(tournament.id, admin.tg_id)
    assert too_early.is_alert
    assert too_early.text == "Сыграно раундов: 0/0."
    results = RoundResultsService(db)
    for round_number in range(1, 4):
        engine.generate_next_round(tournament.id, admin.tg_id)
        for match in results.list_round(tournament.id, round_number):
            if match.player2_user_id is not None:
                results.admin_set(match.id, admin.tg_id, 2, 0)
    engine.generate_next_round(tournament.id, admin.tg_id)
    not_ready = handler.handle_swiss_finish_prompt(tournament.id, admin.tg_id)
    assert not_ready.is_alert
    assert not_ready.text == "Сначала соберите все результаты раунда 4."


def test_swiss_finish_requires_rights(db):
    tournament, users, admin, engine = _internal_setup(db)
    denied = RoundResultsHandler(db).handle_swiss_finish(tournament.id, users[1].tg_id)
    assert denied.is_alert


def test_draft_finish_flow_shows_final_standings(db):
    tournament, users, organizer, engine = _draft_setup(db)
    handler = RoundResultsHandler(db)
    handler.handle_draft_seating(tournament.id, organizer.tg_id)
    results = RoundResultsService(db)
    for round_number in range(1, 4):
        engine.generate_next_round(tournament.id, organizer.tg_id)
        for match in results.list_round(tournament.id, round_number):
            if match.player2_user_id is not None:
                results.admin_set(match.id, organizer.tg_id, 2, 0)
    prompt = handler.handle_swiss_finish_prompt(tournament.id, organizer.tg_id)
    assert not prompt.is_alert
    assert "Завершить турнир" in prompt.text
    finished = handler.handle_swiss_finish(tournament.id, organizer.tg_id)
    assert not finished.is_alert
    assert finished.answer_text == "Турнир завершён."
    standings = handler.handle_swiss_standings(tournament.id, organizer.tg_id)
    assert not standings.is_alert


# --- swiss settings ---


def test_swiss_settings_guards(db):
    tournament, users, admin, _ = _internal_setup(db)
    handler = RoundResultsHandler(db)
    aetherhub = TournamentService(db).create_tournament(TournamentCreate(title="AH", chat_id=100, is_online=True))
    wrong_engine = handler.handle_swiss_settings(aetherhub.id, admin.tg_id)
    assert wrong_engine.is_alert
    assert wrong_engine.text == "Внутренний Swiss-турнир не найден."
    denied = handler.handle_swiss_settings(tournament.id, users[1].tg_id)
    assert denied.is_alert
    assert denied.text == "Нет прав организатора."


def test_swiss_settings_rounds_frozen_after_first_round(db):
    tournament, users, admin, engine = _internal_setup(db)
    engine.generate_next_round(tournament.id, admin.tg_id)
    result = RoundResultsHandler(db).handle_swiss_settings(tournament.id, admin.tg_id)
    assert not result.is_alert
    assert "зафиксированы" in result.text


def test_swiss_settings_draft_line(db):
    tournament, users, organizer, engine = _draft_setup(db)
    result = RoundResultsHandler(db).handle_swiss_settings(tournament.id, organizer.tg_id)
    assert not result.is_alert
    assert "Драфт всегда играет фиксированные три раунда без плей-оффа." in result.text


def test_swiss_settings_large_format_lines(db):
    tournament, users, admin, engine = _internal_setup(db, count=8)
    engine.set_swiss_large_format(tournament.id, admin.tg_id, True)
    engine.set_playoff_size(tournament.id, admin.tg_id, 8)
    handler = RoundResultsHandler(db)
    before = handler.handle_swiss_settings(tournament.id, admin.tg_id)
    assert not before.is_alert
    assert "Плей-офф включается и настраивается до его старта." in before.text
    results = RoundResultsService(db)
    for round_number in range(1, 4):
        engine.generate_next_round(tournament.id, admin.tg_id)
        for match in results.list_round(tournament.id, round_number):
            if match.player2_user_id is not None:
                results.admin_set(match.id, admin.tg_id, 2, 0)
    playoff = engine.generate_next_round(tournament.id, admin.tg_id)
    assert playoff.round_number == 4
    after = handler.handle_swiss_settings(tournament.id, admin.tg_id)
    assert not after.is_alert
    assert "Плей-офф уже начался, размер изменить нельзя." in after.text


def test_swiss_set_large_roundtrip(db):
    tournament, users, admin, _ = _internal_setup(db)
    handler = RoundResultsHandler(db)
    enabled = handler.handle_swiss_set_large(tournament.id, admin.tg_id, True)
    assert not enabled.is_alert
    assert enabled.answer_text is not None and "Большой формат" in enabled.answer_text
    disabled = handler.handle_swiss_set_large(tournament.id, admin.tg_id, False)
    assert not disabled.is_alert
    assert disabled.answer_text is not None and "Классический формат" in disabled.answer_text


def test_swiss_set_rounds_requires_rights(db):
    tournament, users, admin, _ = _internal_setup(db)
    result = RoundResultsHandler(db).handle_swiss_set_rounds(tournament.id, users[1].tg_id, 5)
    assert result.is_alert


def test_swiss_set_playoff_requires_rights(db):
    tournament, users, admin, _ = _internal_setup(db)
    result = RoundResultsHandler(db).handle_swiss_set_playoff(tournament.id, users[1].tg_id, 8)
    assert result.is_alert
