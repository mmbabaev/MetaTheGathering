"""Unit tests for the single-elimination playoff of an internal Swiss event.

The helper plays every match by giving the win to ``player1``. Pairings always
put the better ranked player on the left, so "player1 wins" means the favourite
wins: the Swiss top seeds keep winning and the bracket stays fully predictable.
"""

from __future__ import annotations

import random
from datetime import datetime

import pytest

from bot.handlers.round_results import RoundResultsHandler
from core import models
from core.schemas import TournamentCreate
from services import errors
from services.internal_swiss import (
    PLAYOFF_SIZES,
    InternalSwissService,
    bracket_seed_pairs,
    playoff_rounds,
    recommended_swiss_rounds,
)
from services.round_results import RoundResultError, RoundResultsService
from services.tournament import TournamentService
from services.user import UserService


def _setup(db, count: int = 8, *, large: bool = True):
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
    if large:
        engine.set_swiss_large_format(tournament.id, admin.tg_id, True)
    return tournament, users, admin, engine


def _favourites_win_rounds(db, admin, engine, tournament, swiss_rounds: int):
    """Play the Swiss rounds giving every match to the favourite (player1)."""
    results = RoundResultsService(db)
    for round_number in range(1, swiss_rounds + 1):
        generated = engine.generate_next_round(tournament.id, admin.tg_id)
        assert generated.round_number == round_number
        for match in results.list_round(tournament.id, round_number):
            if match.player2_user_id is not None:
                results.admin_set(match.id, admin.tg_id, 2, 0)


def _swiss_place_map(engine, tournament):
    return {row.user_id: row.place for row in engine.standings(tournament.id)}


def test_bracket_seed_pairs_and_playoff_rounds():
    assert playoff_rounds(0) == 0
    assert playoff_rounds(8) == 3
    assert playoff_rounds(16) == 4
    assert bracket_seed_pairs(2) == [(1, 2)]
    assert bracket_seed_pairs(8) == [(1, 8), (4, 5), (2, 7), (3, 6)]
    assert bracket_seed_pairs(16) == [
        (1, 16),
        (8, 9),
        (4, 13),
        (5, 12),
        (2, 15),
        (7, 10),
        (3, 14),
        (6, 11),
    ]


def test_recommended_rounds_follow_field_size_in_large_format():
    assert recommended_swiss_rounds(50, large_format=True) == 6
    assert recommended_swiss_rounds(100, large_format=True) == 7
    assert recommended_swiss_rounds(1, large_format=True) == 0


def test_set_playoff_size_and_swiss_rounds_guards(db):
    tournament, _users, admin, engine = _setup(db, 8)
    with pytest.raises(RoundResultError, match="Нет прав"):
        engine.set_playoff_size(tournament.id, 999999, 8)
    with pytest.raises(RoundResultError, match="Варианты"):
        engine.set_playoff_size(tournament.id, admin.tg_id, 7)
    assert engine.set_playoff_size(tournament.id, admin.tg_id, 16).playoff_size == 16
    assert engine.set_playoff_size(tournament.id, admin.tg_id, 0).playoff_size is None

    with pytest.raises(RoundResultError, match="от 3 до 20"):
        engine.set_swiss_rounds(tournament.id, admin.tg_id, 2)
    with pytest.raises(RoundResultError, match="от 3 до 20"):
        engine.set_swiss_rounds(tournament.id, admin.tg_id, 21)
    assert engine.set_swiss_rounds(tournament.id, admin.tg_id, 5).swiss_rounds == 5

    engine.generate_next_round(tournament.id, admin.tg_id)
    with pytest.raises(RoundResultError, match="только до первого раунда"):
        engine.set_swiss_rounds(tournament.id, admin.tg_id, 4)


def test_manual_rounds_are_kept_over_recommended(db):
    tournament, _users, admin, engine = _setup(db, 6)
    engine.set_swiss_rounds(tournament.id, admin.tg_id, 5)
    results = RoundResultsService(db)
    for round_number in range(1, 6):
        generated = engine.generate_next_round(tournament.id, admin.tg_id)
        assert generated.round_number == round_number
        assert generated.planned_rounds == 5
        for match in results.list_round(tournament.id, round_number):
            if match.player2_user_id is not None:
                results.admin_set(match.id, admin.tg_id, 2, 0)
    assert db.get(models.Tournament, tournament.id).swiss_rounds == 5
    assert engine.finish(tournament.id, admin.tg_id)


def test_top8_playoff_pairings_seed_bracket_and_final_places(db):
    tournament, _users, admin, engine = _setup(db, 8)
    engine.set_playoff_size(tournament.id, admin.tg_id, 8)
    _favourites_win_rounds(db, admin, engine, tournament, swiss_rounds=3)

    swiss_places = _swiss_place_map(engine, tournament)
    assert sorted(swiss_places.values()) == list(range(1, 9))

    generated = engine.generate_next_round(tournament.id, admin.tg_id)
    assert generated.round_number == 4
    assert generated.planned_rounds == 6
    assert generated.matches == 4

    participants_by_user = {row.user_id: row for row in engine._participants(tournament.id, include_dropped=True)}
    results = RoundResultsService(db)
    quarter = results.list_round(tournament.id, 4)
    actual_pairs = []
    for match in quarter:
        first = participants_by_user[match.player1_user_id].playoff_seed
        second = participants_by_user[match.player2_user_id].playoff_seed
        actual_pairs.append((min(first, second), max(first, second)))
        # Better seed plays first.
        assert first < second
    assert sorted(actual_pairs) == sorted(bracket_seed_pairs(8))

    for match in quarter:
        results.admin_set(match.id, admin.tg_id, 2, 0)
    generated_semi = engine.generate_next_round(tournament.id, admin.tg_id)
    assert generated_semi.round_number == 5
    semi = results.list_round(tournament.id, 5)
    semi_pairs = [
        (
            participants_by_user[match.player1_user_id].playoff_seed,
            participants_by_user[match.player2_user_id].playoff_seed,
        )
        for match in semi
    ]
    assert sorted(frozenset(pair) for pair in semi_pairs) == [frozenset((1, 4)), frozenset((2, 3))]

    for match in semi:
        results.admin_set(match.id, admin.tg_id, 2, 0)
    generated_final = engine.generate_next_round(tournament.id, admin.tg_id)
    assert generated_final.round_number == 6
    finals = results.list_round(tournament.id, 6)
    assert len(finals) == 2
    final_pairs = {
        frozenset(
            (
                participants_by_user[match.player1_user_id].playoff_seed,
                participants_by_user[match.player2_user_id].playoff_seed,
            )
        )
        for match in finals
    }
    assert final_pairs == {frozenset((1, 2)), frozenset((3, 4))}

    # The final (1 vs 2) must place 3rd-vs-4th match after weight: detect by seeds.
    final_match = next(
        match
        for match in finals
        if frozenset(
            (
                participants_by_user[match.player1_user_id].playoff_seed,
                participants_by_user[match.player2_user_id].playoff_seed,
            )
        )
        == frozenset((1, 2))
    )
    third_match = next(match for match in finals if match.id != final_match.id)
    for match in (final_match, third_match):
        results.admin_set(match.id, admin.tg_id, 2, 0)

    standings = engine.finish(tournament.id, admin.tg_id)
    assert [row.place for row in standings] == list(range(1, 9))
    by_user = {row.user_id: row for row in standings}
    for seed in range(1, 9):
        expected_swiss_place = next(user_id for user_id, place in swiss_places.items() if place == seed)
        assert by_user[expected_swiss_place].place == seed

    stored = db.get(models.Tournament, tournament.id)
    assert stored.status == models.TournamentStatus.CLOSED
    assert sorted(participant.final_place for participant in stored.participants) == list(range(1, 9))
    assert sorted(participant.playoff_seed for participant in stored.participants if participant.playoff_seed) == list(
        range(1, 9)
    )


def test_top16_playoff_groups_ranked_by_seed_after_cut(db):
    tournament, _users, admin, engine = _setup(db, 16)
    engine.set_playoff_size(tournament.id, admin.tg_id, 16)
    _favourites_win_rounds(db, admin, engine, tournament, swiss_rounds=4)

    swiss_places = _swiss_place_map(engine, tournament)
    assert sorted(swiss_places.values()) == list(range(1, 17))

    results = RoundResultsService(db)
    for playoff_round in range(5, 9):
        generated = engine.generate_next_round(tournament.id, admin.tg_id)
        assert generated.round_number == playoff_round
        for match in results.list_round(tournament.id, playoff_round):
            if match.player2_user_id is not None:
                results.admin_set(match.id, admin.tg_id, 2, 0)

    standings = engine.finish(tournament.id, admin.tg_id)
    assert [row.place for row in standings] == list(range(1, 17))
    by_user = {row.user_id: row for row in standings}

    # Favourites (player1) always won: the final order equals the Swiss order,
    # with each elimination round's losers ranked by their seed.
    for seed in range(1, 17):
        player = next(user_id for user_id, place in swiss_places.items() if place == seed)
        assert by_user[player].place == seed, seed


def test_playoff_matches_do_not_pollute_swiss_standings(db):
    tournament, _users, admin, engine = _setup(db, 8)
    engine.set_playoff_size(tournament.id, admin.tg_id, 8)
    _favourites_win_rounds(db, admin, engine, tournament, swiss_rounds=3)

    baseline = {row.user_id: (row.match_points, row.record) for row in engine.standings(tournament.id)}

    results = RoundResultsService(db)
    for playoff_round in range(4, 7):
        engine.generate_next_round(tournament.id, admin.tg_id)
        for match in results.list_round(tournament.id, playoff_round):
            if match.player2_user_id is not None:
                results.admin_set(match.id, admin.tg_id, 2, 0)

    # Playoff results never leak into the Swiss-based standings.
    during = {row.user_id: (row.match_points, row.record) for row in engine.standings(tournament.id)}
    assert during == baseline


def test_playoff_rejects_draw_and_finish_requires_last_round(db):
    tournament, _users, admin, engine = _setup(db, 8)
    engine.set_playoff_size(tournament.id, admin.tg_id, 8)
    _favourites_win_rounds(db, admin, engine, tournament, swiss_rounds=3)

    results = RoundResultsService(db)
    generated = engine.generate_next_round(tournament.id, admin.tg_id)
    match = results.list_round(tournament.id, generated.round_number)[0]
    with pytest.raises(RoundResultError, match="ничьей"):
        results.admin_set(match.id, admin.tg_id, 1, 1)
    with pytest.raises(RoundResultError, match="Сыграно"):
        engine.finish(tournament.id, admin.tg_id)


def test_drop_forbidden_after_playoff_starts(db):
    tournament, users, admin, engine = _setup(db, 8)
    engine.set_playoff_size(tournament.id, admin.tg_id, 8)
    _favourites_win_rounds(db, admin, engine, tournament, swiss_rounds=3)
    engine.generate_next_round(tournament.id, admin.tg_id)

    with pytest.raises(errors.TournamentInvalidState, match="плей-офф"):
        TournamentService(db).drop_participant(tournament.id, users[1].id)


def test_playoff_auto_disables_when_field_too_small(db):
    tournament, _users, admin, engine = _setup(db, 8)
    engine.set_playoff_size(tournament.id, admin.tg_id, 16)
    _favourites_win_rounds(db, admin, engine, tournament, swiss_rounds=3)

    with pytest.raises(RoundResultError, match="запланированные"):
        engine.generate_next_round(tournament.id, admin.tg_id)

    standings = engine.finish(tournament.id, admin.tg_id)
    assert [row.place for row in standings] == list(range(1, 9))


def test_playoff_size_change_blocked_after_start(db):
    tournament, _users, admin, engine = _setup(db, 8)
    engine.set_playoff_size(tournament.id, admin.tg_id, 8)
    _favourites_win_rounds(db, admin, engine, tournament, swiss_rounds=3)
    engine.generate_next_round(tournament.id, admin.tg_id)
    with pytest.raises(RoundResultError, match="уже начался"):
        engine.set_playoff_size(tournament.id, admin.tg_id, 16)


def test_settings_screen_rounds_and_playoff(db):
    tournament, _users, admin, engine = _setup(db, 8)
    handler = RoundResultsHandler(db)

    screen = handler.handle_swiss_settings(tournament.id, admin.tg_id)
    assert "⚙️ Настройки Swiss" in screen.text
    assert "Формат: большой" in screen.text
    assert "Swiss-раундов: авто" in screen.text
    assert "Плей-офф: нет" in screen.text
    callbacks = {button.callback_data for row in screen.keyboard.inline_keyboard for button in row}
    assert f"sw_set_l:{tournament.id}:0" in callbacks
    assert f"sw_set_r:{tournament.id}:4" in callbacks
    assert f"sw_set_p:{tournament.id}:8" in callbacks

    rounds_screen = handler.handle_swiss_set_rounds(tournament.id, admin.tg_id, 5)
    assert rounds_screen.answer_text == "Swiss-раундов: 5."
    assert "Swiss-раундов: 5" in rounds_screen.text

    playoff_screen = handler.handle_swiss_set_playoff(tournament.id, admin.tg_id, 8)
    assert playoff_screen.answer_text == "Плей-офф: топ-8."
    assert "Плей-офф: топ-8" in playoff_screen.text

    forbidden = handler.handle_swiss_settings(tournament.id, 999999)
    assert forbidden.is_alert


def test_classic_format_defaults_blocks_tools_and_keeps_four_rounds(db):
    tournament, _users, admin, engine = _setup(db, 8, large=False)

    settings = engine.get_swiss_settings(tournament.id)
    assert settings.large_format is False
    assert settings.recommended_swiss_rounds == 4
    assert engine.effective_playoff_size(db.get(models.Tournament, tournament.id)) == 0

    with pytest.raises(RoundResultError, match="большом формате"):
        engine.set_swiss_rounds(tournament.id, admin.tg_id, 5)
    with pytest.raises(RoundResultError, match="большом формате"):
        engine.set_playoff_size(tournament.id, admin.tg_id, 8)

    handler = RoundResultsHandler(db)
    screen = handler.handle_swiss_settings(tournament.id, admin.tg_id)
    assert "Формат: классический" in screen.text
    callbacks = {button.callback_data for row in screen.keyboard.inline_keyboard for button in row}
    assert f"sw_set_l:{tournament.id}:1" in callbacks
    assert all(not cb.startswith("sw_set_r:") and not cb.startswith("sw_set_p:") for cb in callbacks)

    generated = engine.generate_next_round(tournament.id, admin.tg_id)
    assert (generated.round_number, generated.planned_rounds) == (1, 4)


def test_large_format_toggle_resets_tools_and_is_frozen_after_round_one(db):
    tournament, _users, admin, engine = _setup(db, 8, large=False)

    with pytest.raises(RoundResultError, match="Нет прав"):
        engine.set_swiss_large_format(tournament.id, 999999, True)
    engine.set_swiss_large_format(tournament.id, admin.tg_id, True)
    engine.set_swiss_rounds(tournament.id, admin.tg_id, 5)
    engine.set_playoff_size(tournament.id, admin.tg_id, 8)

    engine.set_swiss_large_format(tournament.id, admin.tg_id, False)
    stored = db.get(models.Tournament, tournament.id)
    assert stored.swiss_large_format is False
    assert stored.swiss_rounds is None
    assert stored.playoff_size is None

    engine.set_swiss_large_format(tournament.id, admin.tg_id, True)
    engine.generate_next_round(tournament.id, admin.tg_id)
    with pytest.raises(RoundResultError, match="только до первого раунда"):
        engine.set_swiss_large_format(tournament.id, admin.tg_id, False)

    handler = RoundResultsHandler(db)
    back = handler.handle_swiss_set_large(tournament.id, admin.tg_id, False)
    assert back.is_alert
    assert "только до первого раунда" in back.text


def test_large_format_rejected_for_draft(db):
    organizer = UserService(db).get_or_create(tg_id=7201, username="draft_owner", first_name="Owner")
    organizer.is_tournament_organizer = True
    tournament = TournamentService(db).create_tournament(
        TournamentCreate(
            title="Endstep draft",
            chat_id=-1002,
            is_online=True,
            is_draft=True,
            engine_mode=models.TournamentEngineMode.INTERNAL_SWISS,
            registration_close_at=datetime(2026, 9, 20, 16, 0),
            created_by_tg_id=organizer.tg_id,
        )
    )
    user = UserService(db).get_or_create(tg_id=7300, first_name="P0")
    TournamentService(db).register_participant(tournament_id=tournament.id, user_id=user.id)
    admin = UserService(db).get_or_create(tg_id=999900, first_name="Admin")
    admin.is_admin = True
    db.commit()
    engine = InternalSwissService(db)

    with pytest.raises(RoundResultError, match="не поддерживает большой формат"):
        engine.set_swiss_large_format(tournament.id, admin.tg_id, True)


def test_finish_prompt_counts_total_planned_with_playoff(db):
    tournament, _users, admin, engine = _setup(db, 8)
    engine.set_playoff_size(tournament.id, admin.tg_id, 8)
    _favourites_win_rounds(db, admin, engine, tournament, swiss_rounds=3)

    handler = RoundResultsHandler(db)
    prompt = handler.handle_swiss_finish_prompt(tournament.id, admin.tg_id)
    assert prompt.is_alert
    assert "Сыграно раундов: 3/6." in prompt.text

    prompt = handler.handle_swiss_finish_prompt(tournament.id, 12345)
    assert prompt.is_alert
    assert prompt.text == "Нет прав."


def test_playoff_round_labels(db):
    tournament, _users, admin, engine = _setup(db, 8)
    engine.set_playoff_size(tournament.id, admin.tg_id, 8)
    tournament = db.get(models.Tournament, tournament.id)
    tournament.swiss_rounds = 4
    assert engine.playoff_round_label(tournament, 3) is None
    assert engine.playoff_round_label(tournament, 5) == "Четвертьфинал"
    assert engine.playoff_round_label(tournament, 6) == "Полуфинал"
    assert engine.playoff_round_label(tournament, 7) == "Финал и матч за 3-е место"

    tournament.playoff_size = 16
    assert engine.playoff_round_label(tournament, 5) == "1/8 финала"


def test_closed_final_standings_use_final_header_and_order(db):
    tournament, _users, admin, engine = _setup(db, 8)
    engine.set_playoff_size(tournament.id, admin.tg_id, 8)
    _favourites_win_rounds(db, admin, engine, tournament, swiss_rounds=3)
    results = RoundResultsService(db)
    for playoff_round in range(4, 7):
        engine.generate_next_round(tournament.id, admin.tg_id)
        for match in results.list_round(tournament.id, playoff_round):
            if match.player2_user_id is not None:
                results.admin_set(match.id, admin.tg_id, 2, 0)
    handler = RoundResultsHandler(db)
    screen = handler.handle_swiss_finish(tournament.id, admin.tg_id)
    assert "🏁 Итоговые места" in screen.text
    assert not screen.is_alert
    # Standings of the closed tournament come back in final order.
    placements = [(row.user_id, row.place) for row in InternalSwissService(db).standings(tournament.id)]
    assert [place for _user_id, place in placements] == list(range(1, 9))


def test_playoff_sizes_constant():
    assert PLAYOFF_SIZES == (8, 16)
