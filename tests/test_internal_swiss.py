from __future__ import annotations

import random

import pytest

from bot.handlers.round_results import RoundResultsHandler
from bot.messages import format_swiss_standings
from core import models
from core.schemas import TournamentCreate
from services import errors
from services.aetherhub_import_service import AetherhubImportService
from services.internal_swiss import InternalSwissService, recommended_swiss_rounds
from services.round_results import RoundResultError, RoundResultsService
from services.tournament import TournamentService
from services.user import UserService


def _setup(db, count: int = 8):
    tournament = TournamentService(db).create_tournament(
        TournamentCreate(title="Internal", chat_id=-1001, club="Endstep-ru", is_online=True)
    )
    users = []
    for index in range(count):
        user = UserService(db).get_or_create(
            tg_id=1000 + index,
            username=f"player{index}",
            first_name=f"Имя{index}",
            last_name=f"Фамилия{index}",
        )
        db.add(models.Participant(tournament_id=tournament.id, user_id=user.id))
        users.append(user)
    admin = users[0]
    admin.is_admin = True
    db.commit()
    engine = InternalSwissService(db, rng=random.Random(7))
    engine.set_enabled(tournament.id, admin.tg_id, True)
    return tournament, users, admin, engine


@pytest.mark.parametrize(
    "players,rounds",
    [(1, 0), (2, 1), (3, 2), (4, 3), (5, 3), (8, 3), (9, 5), (16, 5), (32, 5), (33, 6), (129, 8)],
)
def test_recommended_constructed_rounds_follow_mtr_ranges(players, rounds):
    assert recommended_swiss_rounds(players) == rounds


def test_internal_mode_is_opt_in_and_cannot_replace_existing_pairings(db):
    tournament = TournamentService(db).create_tournament(TournamentCreate(title="External", chat_id=1, is_online=True))
    admin = UserService(db).get_or_create(tg_id=1, first_name="Admin")
    admin.is_admin = True
    db.add(
        models.RoundPairing(
            tournament_id=tournament.id,
            round_number=1,
            player_name="A",
            opponent_name=None,
        )
    )
    db.commit()

    with pytest.raises(RoundResultError, match="уже есть"):
        InternalSwissService(db).set_enabled(tournament.id, admin.tg_id, True)
    assert db.get(models.Tournament, tournament.id).engine_mode == models.TournamentEngineMode.AETHERHUB


def test_first_round_freezes_count_and_uses_exact_registered_identities(db):
    tournament, users, admin, engine = _setup(db, 8)

    generated = engine.generate_next_round(tournament.id, admin.tg_id)

    assert (generated.round_number, generated.planned_rounds, generated.matches) == (1, 3, 4)
    stored = db.get(models.Tournament, tournament.id)
    assert stored.status == models.TournamentStatus.ONGOING
    assert stored.swiss_rounds == 3
    assert sorted(participant.swiss_initial_rank for participant in stored.participants) == list(range(1, 9))
    matches = RoundResultsService(db).list_round(tournament.id, 1)
    assert {match.player1_user_id for match in matches} | {match.player2_user_id for match in matches} == {
        user.id for user in users
    }
    screen = RoundResultsHandler(db).handle_round_status(tournament.id, admin.tg_id)
    assert "Раунд 1/3 · результаты 0/4" in screen.text
    callbacks = {button.callback_data for row in screen.keyboard.inline_keyboard for button in row}
    assert f"sw_table:{tournament.id}:0" in callbacks


def test_next_round_requires_every_result_and_never_repeats_when_avoidable(db):
    tournament, _users, admin, engine = _setup(db, 8)
    engine.generate_next_round(tournament.id, admin.tg_id)
    with pytest.raises(RoundResultError, match="все результаты"):
        engine.generate_next_round(tournament.id, admin.tg_id)

    results = RoundResultsService(db)
    first_pairs = set()
    for index, match in enumerate(results.list_round(tournament.id, 1)):
        first_pairs.add(frozenset((match.player1_user_id, match.player2_user_id)))
        results.admin_set(match.id, admin.tg_id, 2, index % 2)
    engine.generate_next_round(tournament.id, admin.tg_id)
    second_pairs = {
        frozenset((match.player1_user_id, match.player2_user_id)) for match in results.list_round(tournament.id, 2)
    }
    assert first_pairs.isdisjoint(second_pairs)
    old_screen = RoundResultsHandler(db).handle_round_status(tournament.id, admin.tg_id, 1)
    old_callbacks = {button.callback_data for row in old_screen.keyboard.inline_keyboard for button in row}
    assert f"sw_next:{tournament.id}" not in old_callbacks


def test_aetherhub_import_cannot_overwrite_internal_tournament(db):
    tournament, _users, _admin, _engine = _setup(db, 4)

    with pytest.raises(errors.TournamentInvalidState, match="импорт AetherHub отключён"):
        AetherhubImportService(db).import_tournament(tournament.id, object())


def test_odd_event_gives_bye_to_lowest_ranked_player_without_prior_bye(db):
    tournament, _users, admin, engine = _setup(db, 7)
    engine.generate_next_round(tournament.id, admin.tg_id)
    results = RoundResultsService(db)
    first = results.list_round(tournament.id, 1)
    first_bye = next(match.player1_user_id for match in first if match.player2_user_id is None)
    for match in first:
        if match.player2_user_id is not None:
            results.admin_set(match.id, admin.tg_id, 2, 0)

    before_second = engine.standings(tournament.id)
    eligible = [row for row in before_second if row.user_id != first_bye]
    expected_bye = max(eligible, key=lambda row: row.place).user_id
    engine.generate_next_round(tournament.id, admin.tg_id)
    second = results.list_round(tournament.id, 2)
    second_bye = next(match.player1_user_id for match in second if match.player2_user_id is None)

    assert second_bye == expected_bye
    assert second_bye != first_bye


def test_official_tiebreakers_and_bye_are_calculated(db):
    tournament, _users, admin, engine = _setup(db, 5)
    engine.generate_next_round(tournament.id, admin.tg_id)
    results = RoundResultsService(db)
    bye = next(match for match in results.list_round(tournament.id, 1) if match.player2_user_id is None)
    for match in results.list_round(tournament.id, 1):
        if match.player2_user_id is not None:
            results.admin_set(match.id, admin.tg_id, 1, 1)

    standings = engine.standings(tournament.id)
    bye_row = next(row for row in standings if row.user_id == bye.player1_user_id)
    draw_rows = [row for row in standings if row.user_id != bye.player1_user_id]

    assert (bye_row.match_points, bye_row.wins, bye_row.byes) == (3, 1, 1)
    assert bye_row.game_win_percentage == 1.0
    assert bye_row.opponents_match_win_percentage == 0.0
    assert all(row.match_points == 1 and row.record == "0–0–1" for row in draw_rows)
    assert all(row.game_win_percentage == pytest.approx(4 / 9) for row in draw_rows)
    text = format_swiss_standings("Internal", 1, 3, standings, provisional=False)
    assert "BYE ×1" in text
    assert "OMW" in text and "GW" in text and "OGW" in text


def test_odd_score_groups_create_only_one_pair_up_pair_down(db):
    tournament, _users, admin, engine = _setup(db, 6)
    engine.generate_next_round(tournament.id, admin.tg_id)
    results = RoundResultsService(db)
    for match in results.list_round(tournament.id, 1):
        results.admin_set(match.id, admin.tg_id, 2, 0)
    points = {row.user_id: row.match_points for row in engine.standings(tournament.id)}

    engine.generate_next_round(tournament.id, admin.tg_id)
    gaps = [
        abs(points[match.player1_user_id] - points[match.player2_user_id])
        for match in results.list_round(tournament.id, 2)
    ]

    assert sorted(gaps) == [0, 0, 3]


def test_five_round_internal_event_finishes_and_persists_places(db):
    tournament, _users, admin, engine = _setup(db, 9)
    results = RoundResultsService(db)
    for expected_round in range(1, 6):
        generated = engine.generate_next_round(tournament.id, admin.tg_id)
        assert generated.round_number == expected_round
        for match in results.list_round(tournament.id, expected_round):
            if match.player2_user_id is not None:
                results.admin_set(match.id, admin.tg_id, 2, 0)

    with pytest.raises(RoundResultError, match="запланированные"):
        engine.generate_next_round(tournament.id, admin.tg_id)
    standings = engine.finish(tournament.id, admin.tg_id)

    stored = db.get(models.Tournament, tournament.id)
    assert stored.status == models.TournamentStatus.CLOSED
    assert [row.place for row in standings] == list(range(1, 10))
    assert sorted(participant.final_place for participant in stored.participants) == list(range(1, 10))


def test_fifteen_player_debug_sized_event_has_unique_matches_and_byes(db):
    tournament, _users, admin, engine = _setup(db, 15)
    results = RoundResultsService(db)
    score_rng = random.Random(19)
    seen_pairs: set[frozenset[int]] = set()
    seen_byes: set[int] = set()

    for round_number in range(1, 6):
        generated = engine.generate_next_round(tournament.id, admin.tg_id)
        assert generated.round_number == round_number
        for match in results.list_round(tournament.id, round_number):
            if match.player2_user_id is None:
                assert match.player1_user_id not in seen_byes
                seen_byes.add(match.player1_user_id)
                continue
            pair = frozenset((match.player1_user_id, match.player2_user_id))
            assert pair not in seen_pairs
            seen_pairs.add(pair)
            results.admin_set(match.id, admin.tg_id, *score_rng.choice(((2, 0), (2, 1), (1, 1), (0, 2))))

    assert len(seen_pairs) == 35
    assert len(seen_byes) == 5
