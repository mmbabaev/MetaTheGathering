from __future__ import annotations

import random

import pytest
from sqlalchemy import select

from bot.handlers.round_results import RoundResultsHandler
from bot.messages import format_aetherhub_round_summary, format_round_pairings
from core import models
from core.schemas import TournamentCreate
from services.aetherhub_import_service import AetherhubImportService
from services.aetherhub_models import AetherhubPairing, AetherhubRound, AetherhubTournamentData
from services.debug_tournament import DebugTournamentService
from services.round_results import RoundResultError, RoundResultsService
from services.tournament import TournamentService
from services.user import UserService


def _online_tournament(db):
    return TournamentService(db).create_tournament(TournamentCreate(title="Endstep Test", chat_id=100, is_online=True))


def _user(db, tg_id, first, last, *, username=None, admin=False):
    user = UserService(db).get_or_create(tg_id=tg_id, username=username, first_name=first, last_name=last)
    user.is_admin = admin
    db.commit()
    return user


def _participant(db, tournament_id, user):
    db.add(models.Participant(tournament_id=tournament_id, user_id=user.id))
    db.commit()


def _round(db, tournament_id, number, left, right, table=1, score=None):
    left_score, right_score = score or (None, None)
    db.add_all(
        [
            models.RoundPairing(
                tournament_id=tournament_id,
                round_number=number,
                table_number=table,
                player_name=left,
                opponent_name=right,
                player_wins=left_score,
                opponent_wins=right_score,
            ),
            models.RoundPairing(
                tournament_id=tournament_id,
                round_number=number,
                table_number=table,
                player_name=right,
                opponent_name=left,
                player_wins=right_score,
                opponent_wins=left_score,
            ),
        ]
    )
    db.commit()


@pytest.fixture
def online_match(db):
    tournament = _online_tournament(db)
    alice = _user(db, 101, "Алиса", "Иванова", username="alice_tg")
    bob = _user(db, 102, "Борис", "Петров", username="bob_tg")
    _participant(db, tournament.id, alice)
    _participant(db, tournament.id, bob)
    _round(db, tournament.id, 1, "Иванова Алиса", "Петров Борис")
    match = RoundResultsService(db).sync_round(tournament.id, 1)[0]
    return tournament, alice, bob, match


def test_sync_builds_one_canonical_match_from_reciprocal_pairings(db, online_match):
    tournament, alice, bob, match = online_match
    assert match.player1_name == "Иванова Алиса"
    assert match.player2_name == "Петров Борис"
    assert match.player1_user_id == alice.id
    assert match.player2_user_id == bob.id
    assert len(RoundResultsService(db).list_round(tournament.id, 1)) == 1


def test_player2_proposal_is_stored_in_source_order_and_not_exported_until_confirmed(db, online_match):
    tournament, alice, bob, match = online_match
    proposed = RoundResultsService(db).propose(match.id, bob.tg_id, own_wins=1, opponent_wins=2)
    assert (proposed.player1_wins, proposed.player2_wins) == (2, 1)
    assert proposed.status == models.RoundMatchStatus.PENDING
    pairings = AetherhubImportService(db).get_pairings(tournament.id, 1)
    assert all(row.player_wins is None for row in pairings)


def test_opponent_confirmation_updates_both_export_pairing_directions(db, online_match):
    tournament, alice, bob, match = online_match
    proposed = RoundResultsService(db).propose(match.id, alice.tg_id, 2, 1)
    confirmed = RoundResultsService(db).confirm(match.id, proposed.revision, bob.tg_id)
    assert confirmed.status == models.RoundMatchStatus.CONFIRMED
    rows = {row.player_name: row for row in AetherhubImportService(db).get_pairings(tournament.id, 1)}
    assert (rows["Иванова Алиса"].player_wins, rows["Иванова Алиса"].opponent_wins) == (2, 1)
    assert (rows["Петров Борис"].player_wins, rows["Петров Борис"].opponent_wins) == (1, 2)
    assert [event.event_type for event in confirmed.events] == ["proposed", "confirmed"]


def test_proposer_cannot_confirm_and_stale_button_cannot_confirm_new_proposal(db, online_match):
    _, alice, bob, match = online_match
    results = RoundResultsService(db)
    first = results.propose(match.id, alice.tg_id, 2, 0)
    with pytest.raises(RoundResultError, match="соперник"):
        results.confirm(match.id, first.revision, alice.tg_id)
    rejected = results.reject(match.id, first.revision, bob.tg_id)
    stale_revision = rejected.match.revision
    second = results.propose(match.id, bob.tg_id, 1, 1)
    with pytest.raises(RoundResultError, match="неактуально"):
        results.confirm(match.id, stale_revision, alice.tg_id)
    results.confirm(match.id, second.revision, alice.tg_id)


def test_rejection_resets_active_score_and_opens_corrected_two_step_flow(db, online_match):
    _, alice, bob, match = online_match
    handler = RoundResultsHandler(db)
    delivery = handler.handle_send(match.id, alice.tg_id, 2, 0)
    assert delivery.recipient_tg_id == bob.tg_id
    rejected = handler.handle_reject(match.id, db.get(models.RoundMatch, match.id).revision, bob.tg_id)
    assert rejected.recipient_tg_id == alice.tg_id
    assert "Укажите правильный" in rejected.screen.text
    reset = db.get(models.RoundMatch, match.id)
    assert reset.status == models.RoundMatchStatus.UNREPORTED
    assert reset.player1_wins is None


def test_invalid_2_2_is_hidden_after_two_and_rejected_by_service(db, online_match):
    tournament, alice, _, match = online_match
    screen = RoundResultsHandler(db).handle_own_wins(match.id, alice.tg_id, 2)
    assert [button.text for button in screen.keyboard.inline_keyboard[0]] == ["0", "1"]
    assert screen.keyboard.inline_keyboard[1][0].callback_data == f"rr_open:{tournament.id}"
    with pytest.raises(RoundResultError, match="2–2"):
        RoundResultsService(db).propose(match.id, alice.tg_id, 2, 2)


def test_result_entry_and_admin_score_steps_have_logical_back_buttons(db, online_match):
    tournament, alice, _bob, match = online_match
    handler = RoundResultsHandler(db)

    own_step = handler.handle_open(tournament.id, alice.tg_id)
    assert own_step.keyboard.inline_keyboard[-1][0].callback_data == f"t:{tournament.id}"

    opponent_step = handler.handle_own_wins(match.id, alice.tg_id, 1)
    assert opponent_step.keyboard.inline_keyboard[-1][0].callback_data == f"rr_open:{tournament.id}"

    delivery = handler.handle_send(match.id, alice.tg_id, 1, 1)
    assert delivery.screen.keyboard.inline_keyboard[-1][0].callback_data == f"t:{tournament.id}"
    assert delivery.recipient_keyboard.inline_keyboard[-1][0].callback_data == f"t:{tournament.id}"

    confirmed = handler.handle_confirm(match.id, db.get(models.RoundMatch, match.id).revision, _bob.tg_id)
    assert confirmed.screen.keyboard.inline_keyboard[-1][0].callback_data == f"t:{tournament.id}"
    assert confirmed.recipient_keyboard.inline_keyboard[-1][0].callback_data == f"t:{tournament.id}"

    admin = _user(db, 999, "Анна", "Админова", admin=True)
    admin_first_step = handler.handle_admin_match(match.id, admin.tg_id)
    assert admin_first_step.keyboard.inline_keyboard[-1][0].callback_data == f"rr_admin:{tournament.id}"

    admin_second_step = handler.handle_admin_p1(match.id, admin.tg_id, 1)
    assert admin_second_step.keyboard.inline_keyboard[-1][0].callback_data == f"rr_adm_m:{match.id}"


def test_result_open_always_returns_to_tournament(db, online_match):
    tournament, alice, bob, match = online_match
    handler = RoundResultsHandler(db)
    expected_callback = f"t:{tournament.id}"

    pending = RoundResultsService(db).propose(match.id, alice.tg_id, 2, 1)
    waiting = handler.handle_open(tournament.id, alice.tg_id)
    confirmation = handler.handle_open(tournament.id, bob.tg_id)

    assert waiting.keyboard.inline_keyboard[-1][0].callback_data == expected_callback
    assert confirmation.keyboard.inline_keyboard[-1][0].callback_data == expected_callback

    RoundResultsService(db).confirm(match.id, pending.revision, bob.tg_id)
    completed = handler.handle_open(tournament.id, alice.tg_id)

    assert "Результат уже подтверждён" in completed.text
    assert completed.keyboard.inline_keyboard[-1][0].callback_data == expected_callback


def test_result_open_error_returns_message_with_tournament_button(db, online_match):
    tournament, _alice, _bob, _match = online_match
    outsider = _user(db, 103, "Вера", "Сидорова")

    screen = RoundResultsHandler(db).handle_open(tournament.id, outsider.tg_id)

    assert screen.is_alert is False
    assert len(screen.keyboard.inline_keyboard) == 1
    assert len(screen.keyboard.inline_keyboard[0]) == 1
    assert screen.keyboard.inline_keyboard[0][0].text == "⬅️ К турниру"
    assert screen.keyboard.inline_keyboard[0][0].callback_data == f"t:{tournament.id}"


def test_result_open_bye_returns_message_with_tournament_button(db, online_match):
    tournament, alice, _bob, match = online_match
    match.player2_name = None
    match.player2_user_id = None
    match.status = models.RoundMatchStatus.IMPORTED
    db.commit()

    screen = RoundResultsHandler(db).handle_open(tournament.id, alice.tg_id)

    assert "у вас BYE" in screen.text
    assert screen.keyboard.inline_keyboard[0][0].callback_data == f"t:{tournament.id}"


def test_admin_can_set_and_replace_result(db, online_match):
    tournament, _, _, match = online_match
    admin = _user(db, 999, "Анна", "Админова", admin=True)
    saved = RoundResultsService(db).admin_set(match.id, admin.tg_id, 1, 0)
    assert saved.status == models.RoundMatchStatus.ADMIN
    assert RoundResultsService(db).is_round_ready(tournament.id)
    replaced = RoundResultsService(db).admin_set(match.id, admin.tg_id, 0, 2)
    assert (replaced.player1_wins, replaced.player2_wins) == (0, 2)
    assert [event.event_type for event in replaced.events] == ["admin_set", "admin_set"]


def test_pending_score_is_public_and_summary_keeps_source_order(db, online_match):
    tournament, alice, _, match = online_match
    pending = RoundResultsService(db).propose(match.id, alice.tg_id, 1, 0)
    text = format_round_pairings(tournament.title, "Идёт", 1, [pending])
    assert "1. @alice_tg — @bob_tg" in text
    assert "   Иванова Алиса — Петров Борис" in text
    assert "Счёт: <b>1–0</b> · Статус: ⏳ ожидает подтверждения" in text
    summary = format_aetherhub_round_summary(1, [pending])
    assert "Иванова Алиса 1-0 Петров Борис" in summary


def test_unreported_match_has_explicit_status_and_name_fallback(db):
    tournament = _online_tournament(db)
    alice = _user(db, 111, "Алиса", "Иванова")
    bob = _user(db, 112, "Борис", "Петров")
    _participant(db, tournament.id, alice)
    _participant(db, tournament.id, bob)
    _round(db, tournament.id, 1, "Иванова Алиса", "Петров Борис")
    match = RoundResultsService(db).sync_round(tournament.id, 1)[0]

    text = format_round_pairings(tournament.title, "Идёт", 1, [match])

    assert "1. Иванова — Петров" in text
    assert "   Иванова Алиса — Петров Борис" in text
    assert "Счёт: — · Статус: 🎮 играют" in text
    assert "✅ подтверждено · ⏳ ожидает соперника" not in text


def test_tournament_pairing_view_toggle_controls_public_round_screen(db, online_match):
    tournament, alice, _, _ = online_match
    alice.is_admin = True
    db.commit()
    handler = RoundResultsHandler(db)
    toggled = handler.handle_toggle_view(tournament.id, alice.tg_id)
    assert toggled.is_alert is False
    assert db.get(models.Tournament, tournament.id).show_round_pairings is True
    screen = handler.handle_round_status(tournament.id, alice.tg_id)
    assert "Раунд 1 · результаты 0/1" in screen.text
    assert len(screen.text) < 4096


def test_blank_aetherhub_reimport_does_not_erase_confirmed_local_score(db, online_match):
    tournament, alice, bob, match = online_match
    results = RoundResultsService(db)
    proposed = results.propose(match.id, alice.tg_id, 2, 1)
    results.confirm(match.id, proposed.revision, bob.tg_id)
    data = AetherhubTournamentData(
        url="https://example.invalid/tournament",
        players=["Иванова Алиса", "Петров Борис"],
        rounds=[
            AetherhubRound(
                number=1,
                pairings=[
                    AetherhubPairing("Иванова Алиса", "Петров Борис", 1),
                    AetherhubPairing("Петров Борис", "Иванова Алиса", 1),
                ],
            )
        ],
    )
    AetherhubImportService(db).import_tournament(tournament.id, data)
    rows = {row.player_name: row for row in AetherhubImportService(db).get_pairings(tournament.id, 1)}
    assert (rows["Иванова Алиса"].player_wins, rows["Иванова Алиса"].opponent_wins) == (2, 1)


def test_completed_current_round_does_not_finish_online_tournament_early(db):
    tournament = _online_tournament(db)
    users = [_user(db, 200 + index, f"Игрок{index}", f"Фамилия{index}", admin=index == 0) for index in range(4)]
    for user in users:
        _participant(db, tournament.id, user)
    _round(db, tournament.id, 1, "Фамилия0 Игрок0", "Фамилия1 Игрок1", table=1)
    _round(db, tournament.id, 1, "Фамилия2 Игрок2", "Фамилия3 Игрок3", table=2)
    results = RoundResultsService(db)
    matches = results.sync_round(tournament.id, 1)
    for match in matches:
        results.admin_set(match.id, users[0].tg_id, 2, 0)
    assert AetherhubImportService(db).is_tournament_complete(tournament.id) is False


def test_debug_fill_is_idempotent_and_enables_online_pairing_view(db):
    tournament = TournamentService(db).create_tournament(TournamentCreate(title="Debug", chat_id=5))
    debug = DebugTournamentService(db, rng=random.Random(1))
    first = debug.fill_to_15(tournament.id)
    second = debug.fill_to_15(tournament.id)
    assert (first.added, first.total) == (7, 7)
    assert (second.added, second.total) == (0, 7)
    stored = db.get(models.Tournament, tournament.id)
    assert stored.is_online is True
    assert stored.show_round_pairings is True


def test_debug_refill_does_not_reuse_removed_synthetic_identity(db):
    tournament = TournamentService(db).create_tournament(TournamentCreate(title="Debug", chat_id=5))
    debug = DebugTournamentService(db, rng=random.Random(1))
    debug.fill_to_15(tournament.id)
    removed = (
        db.execute(
            select(models.Participant)
            .where(models.Participant.tournament_id == tournament.id)
            .order_by(models.Participant.id)
        )
        .scalars()
        .first()
    )
    removed_username = removed.user.username
    db.delete(removed)
    db.commit()

    refill = debug.fill_to_15(tournament.id)

    usernames = [participant.user.username for participant in debug._participants(tournament.id)]
    assert refill.added == 1
    assert removed_username not in usernames
    assert len(set(usernames)) == 7


def test_debug_next_round_completes_previous_and_builds_score_aware_pairings(db):
    tournament = TournamentService(db).create_tournament(TournamentCreate(title="Debug", chat_id=5))
    admin = _user(db, 999, "Анна", "Админова", admin=True)
    debug = DebugTournamentService(db, rng=random.Random(7))
    debug.fill_to_15(tournament.id)
    first = debug.next_round(tournament.id, admin.tg_id)
    second = debug.next_round(tournament.id, admin.tg_id)
    assert (first.round_number, first.matches, first.completed_previous) == (1, 4, 0)
    assert (second.round_number, second.matches, second.completed_previous) == (2, 4, 3)
    round_one = RoundResultsService(db).list_round(tournament.id, 1)
    assert sum(match.player2_name is None for match in round_one) == 1
    assert all(match.player2_name is None or match.status == models.RoundMatchStatus.ADMIN for match in round_one)
    round_two = RoundResultsService(db).list_round(tournament.id, 2)
    assert sum(match.player2_name is None for match in round_two) == 1
    assert db.get(models.Tournament, tournament.id).status == models.TournamentStatus.ONGOING
