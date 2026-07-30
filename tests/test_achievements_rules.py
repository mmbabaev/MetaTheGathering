"""Правила ачивок: что засчитывается, что нет и какие причины показываются.

Турниры собираем вручную из парингов — так же, как это делают тесты отбивки
«сбор метагейма завершён»: реализм «кто кого побил» для арифметики не важен.
"""

from datetime import timedelta

import pytest

from core import models
from core.schemas import TournamentCreate
from services.achievements import AchievementService
from services.achievements.definitions import Codes
from services.achievements.rules import (
    ClubTouristRule,
    CollectorRule,
    DebutRule,
    DeckRule,
    FirstDeckRule,
    LastDeckRule,
    LoyalistRule,
    MulticlassRule,
    RegularRule,
    ResilientRule,
    RevengeRule,
    ScribeRule,
    UndefeatedRule,
)
from services.tournament import TournamentService


def _tournament(db, title, *, club="Goldfish", days_ago=0):
    svc = TournamentService(db)
    # на чат допустим только один незакрытый турнир — прошлые закрываем, как в жизни
    active = (
        db.query(models.Tournament)
        .filter(models.Tournament.chat_id == 100, models.Tournament.status != models.TournamentStatus.CLOSED)
        .first()
    )
    if active is not None:
        svc.close_tournament(active.id)
    created = svc.create_tournament(TournamentCreate(title=title, chat_id=100))
    t = db.get(models.Tournament, created.id)  # create_tournament отдаёт схему, нам нужна ORM-строка
    t.club = club
    t.started_at = models.utc_now() - timedelta(days=days_ago)
    db.commit()
    return t


def _register(db, tournament, user, archetype=None, *, self_recorded=True, admin=False):
    TournamentService(db).register_participant(
        tournament_id=tournament.id,
        user_id=user.id,
        archetype_id=archetype.id if archetype else None,
        added_by_admin=admin,
        deck_added_by_tg_id=(user.tg_id if self_recorded else 999999) if archetype else None,
    )


def _rounds(db, tournament, player_name, results):
    """results — список (player_wins, opponent_wins); None-оппонент = бай."""
    for i, (pw, ow) in enumerate(results, start=1):
        db.add(
            models.RoundPairing(
                tournament_id=tournament.id,
                round_number=i,
                player_name=player_name,
                opponent_name=f"Opp{i}",
                table_number=i,
                player_wins=pw,
                opponent_wins=ow,
            )
        )
    db.commit()


def _named_user(user_svc, tg_id, first, last):
    return user_svc.get_or_create(tg_id=tg_id, first_name=first, last_name=last)


@pytest.fixture
def alice(user_svc):
    return _named_user(user_svc, 5001, "Алиса", "Иванова")


@pytest.fixture
def bob(user_svc):
    return _named_user(user_svc, 5002, "Боб", "Петров")


def _ctx(db, tournament_id):
    return AchievementService(db).build_context(tournament_id)


# --------------------------------------------------------------------- Дебют


def test_debut_awarded_on_first_self_recorded_tournament(db, alice, archetype_burn):
    t = _tournament(db, "Pauper 1")
    _register(db, t, alice, archetype_burn)
    _rounds(db, t, "Иванова Алиса", [(2, 0)])

    outcome = DebutRule().evaluate(_ctx(db, t.id))

    assert [a.code for a in outcome.awards] == [Codes.DEBUT]
    assert "Burn" in outcome.awards[0].evidence


def test_debut_not_awarded_twice(db, alice, archetype_burn):
    first = _tournament(db, "Pauper 1", days_ago=7)
    _register(db, first, alice, archetype_burn)
    _rounds(db, first, "Иванова Алиса", [(2, 0)])
    second = _tournament(db, "Pauper 2")
    _register(db, second, alice, archetype_burn)
    _rounds(db, second, "Иванова Алиса", [(2, 0)])

    assert DebutRule().evaluate(_ctx(db, second.id)).awards == []


def test_deck_recorded_by_admin_is_not_counted(db, alice, archetype_burn):
    t = _tournament(db, "Pauper 1")
    _register(db, t, alice, archetype_burn, self_recorded=False, admin=True)
    _rounds(db, t, "Иванова Алиса", [(2, 0)])

    ctx = _ctx(db, t.id)

    assert ctx.eligible_user_ids == set()
    assert DebutRule().evaluate(ctx).awards == []
    assert [s.reason for s in ctx.skipped] == ["колоду записал не он"]


# --------------------------------------------------------------- Без поражений


def test_undefeated_counts_only_clean_sweeps(db, alice, archetype_burn):
    t = _tournament(db, "Pauper 1")
    _register(db, t, alice, archetype_burn)
    _rounds(db, t, "Иванова Алиса", [(2, 0), (2, 1), (2, 0), (2, 0)])

    outcome = UndefeatedRule().evaluate(_ctx(db, t.id))

    assert [(a.code, a.level) for a in outcome.awards] == [(Codes.UNDEFEATED, 1)]
    assert outcome.awards[0].progress_value == 1
    assert "4-0" in outcome.awards[0].evidence


def test_undefeated_not_awarded_with_a_loss(db, alice, archetype_burn):
    t = _tournament(db, "Pauper 1")
    _register(db, t, alice, archetype_burn)
    _rounds(db, t, "Иванова Алиса", [(2, 0), (0, 2)])

    assert UndefeatedRule().evaluate(_ctx(db, t.id)).awards == []


def test_undefeated_progress_accumulates_across_tournaments(db, alice, archetype_burn):
    for i in range(2):
        t = _tournament(db, f"Pauper {i}", days_ago=10 - i)
        _register(db, t, alice, archetype_burn)
        _rounds(db, t, "Иванова Алиса", [(2, 0), (2, 0)])

    outcome = UndefeatedRule().evaluate(_ctx(db, t.id))

    assert outcome.progress[0].value == 2
    assert outcome.progress[0].threshold == 3  # следующий уровень — «Без поражений II»


# ------------------------------------------------------------------ Метаписец


def test_scribe_counts_only_other_players_decks(db, alice, bob, archetype_burn, archetype_affinity):
    t = _tournament(db, "Pauper 1")
    _register(db, t, alice, archetype_burn)  # свою записала сама — не считается
    TournamentService(db).register_participant(
        tournament_id=t.id, user_id=bob.id, archetype_id=archetype_affinity.id, deck_added_by_tg_id=alice.tg_id
    )
    _rounds(db, t, "Иванова Алиса", [(2, 0)])

    outcome = ScribeRule().evaluate(_ctx(db, t.id))
    progress = [p for p in outcome.progress if p.user_id == alice.id]

    assert progress[0].value == 1
    assert "Петров Боб" in progress[0].evidence


# ---------------------------------------------------------------- Завсегдатай


def test_regular_streak_counts_consecutive_club_tournaments(db, alice, archetype_burn):
    for i in range(4):
        t = _tournament(db, f"Pauper {i}", days_ago=30 - i * 7)
        _register(db, t, alice, archetype_burn)
        _rounds(db, t, "Иванова Алиса", [(2, 0)])

    outcome = RegularRule().evaluate(_ctx(db, t.id))

    assert [(a.code, a.level) for a in outcome.awards] == [(Codes.REGULAR, 1)]
    assert outcome.awards[0].progress_value == 4


def test_regular_streak_breaks_on_missed_tournament(db, alice, bob, archetype_burn):
    for i in range(4):
        t = _tournament(db, f"Pauper {i}", days_ago=30 - i * 7)
        if i == 1:
            _register(db, t, bob, archetype_burn)  # турнир состоялся, Алиса пропустила
            _rounds(db, t, "Петров Боб", [(2, 0)])
            continue
        _register(db, t, alice, archetype_burn)
        _rounds(db, t, "Иванова Алиса", [(2, 0)])

    outcome = RegularRule().evaluate(_ctx(db, t.id))

    assert outcome.awards == []
    assert [p.value for p in outcome.progress if p.user_id == alice.id] == [2]


def test_regular_ignores_tournaments_without_club(db, alice, archetype_burn):
    t = _tournament(db, "Pauper 1", club=None)
    _register(db, t, alice, archetype_burn)
    _rounds(db, t, "Иванова Алиса", [(2, 0)])

    outcome = RegularRule().evaluate(_ctx(db, t.id))

    assert outcome.awards == [] and outcome.progress == []


# ----------------------------------------------------------------- Мультикласс


def test_multiclass_counts_distinct_decks_in_window(db, alice, archetype_burn, archetype_affinity):
    first = _tournament(db, "Pauper 1", days_ago=20)
    _register(db, first, alice, archetype_burn)
    _rounds(db, first, "Иванова Алиса", [(2, 0)])
    second = _tournament(db, "Pauper 2", days_ago=10)
    _register(db, second, alice, archetype_affinity)
    _rounds(db, second, "Иванова Алиса", [(2, 0)])

    outcome = MulticlassRule().evaluate(_ctx(db, second.id))

    assert [p.value for p in outcome.progress] == [2]
    assert [p.threshold for p in outcome.progress] == [3]


def test_multiclass_ignores_decks_outside_window(db, alice, archetype_burn, archetype_affinity):
    old = _tournament(db, "Pauper old", days_ago=200)
    _register(db, old, alice, archetype_burn)
    _rounds(db, old, "Иванова Алиса", [(2, 0)])
    recent = _tournament(db, "Pauper new", days_ago=1)
    _register(db, recent, alice, archetype_affinity)
    _rounds(db, recent, "Иванова Алиса", [(2, 0)])

    outcome = MulticlassRule().evaluate(_ctx(db, recent.id))

    assert [p.value for p in outcome.progress] == [1]


# -------------------------------------------------------------------- Однолюб


def test_loyalist_streak_on_same_deck(db, alice, archetype_burn):
    for i in range(3):
        t = _tournament(db, f"Pauper {i}", days_ago=20 - i * 7)
        _register(db, t, alice, archetype_burn)
        _rounds(db, t, "Иванова Алиса", [(2, 0)])

    outcome = LoyalistRule().evaluate(_ctx(db, t.id))

    assert [(a.code, a.level) for a in outcome.awards] == [(Codes.LOYALIST, 1)]
    assert "Burn" in outcome.awards[0].evidence


def test_loyalist_streak_resets_on_deck_change(db, alice, archetype_burn, archetype_affinity):
    for i, arch in enumerate((archetype_burn, archetype_burn, archetype_affinity)):
        t = _tournament(db, f"Pauper {i}", days_ago=20 - i * 7)
        _register(db, t, alice, arch)
        _rounds(db, t, "Иванова Алиса", [(2, 0)])

    outcome = LoyalistRule().evaluate(_ctx(db, t.id))

    assert outcome.awards == []
    assert [p.value for p in outcome.progress] == [1]


# --------------------------------------------------------------- Буду первый


def test_first_deck_goes_to_the_earliest_recorder(db, alice, bob, archetype_burn, archetype_affinity):
    t = _tournament(db, "Pauper 1")
    _register(db, t, alice, archetype_burn)
    _register(db, t, bob, archetype_affinity)
    alice_participant = db.query(models.Participant).filter_by(tournament_id=t.id, user_id=alice.id).one()
    alice_participant.created_at = models.utc_now() - timedelta(hours=2)
    db.commit()
    _rounds(db, t, "Иванова Алиса", [(2, 0)])
    _rounds(db, t, "Петров Боб", [(0, 2)])

    outcome = FirstDeckRule().evaluate(_ctx(db, t.id))

    assert [(a.user_id, a.level) for a in outcome.awards] == [(alice.id, 1)]
    assert "первым записал колоду сегодня" in outcome.awards[0].evidence


# ── ачивки по колодам ────────────────────────────────────────────────────────


def test_deck_achievement_awarded_for_played_deck(db, alice, arch_svc):
    tron = arch_svc.get_or_create_by_name("Monster Tron")
    t = _tournament(db, "Pauper 1")
    _register(db, t, alice, tron)
    _rounds(db, t, "Иванова Алиса", [(2, 0)])

    outcome = DeckRule().evaluate(_ctx(db, t.id))

    assert [a.code for a in outcome.awards] == ["deck_tron"]
    assert "Monster Tron" in outcome.awards[0].evidence


def test_deck_achievement_matches_synonyms(db, alice, arch_svc):
    """«Blue Delver» — это тот же Terror: сопоставляем по общему типу, а не по строке."""
    delver = arch_svc.get_or_create_by_name("Blue Delver")
    t = _tournament(db, "Pauper 1")
    _register(db, t, alice, delver)
    _rounds(db, t, "Иванова Алиса", [(2, 0)])

    assert [a.code for a in DeckRule().evaluate(_ctx(db, t.id)).awards] == ["deck_terror"]


def test_unknown_deck_gives_no_deck_achievement(db, alice, arch_svc):
    exotic = arch_svc.get_or_create_by_name("Совершенно своя дека")
    t = _tournament(db, "Pauper 1")
    _register(db, t, alice, exotic)
    _rounds(db, t, "Иванова Алиса", [(2, 0)])

    assert DeckRule().evaluate(_ctx(db, t.id)).awards == []


def test_deck_achievements_accumulate_across_tournaments(db, alice, arch_svc):
    for i, name in enumerate(("Tron", "Elves", "Burn")):
        archetype = arch_svc.get_or_create_by_name(name)
        t = _tournament(db, f"Pauper {i}", days_ago=20 - i * 7)
        _register(db, t, alice, archetype)
        _rounds(db, t, "Иванова Алиса", [(2, 0)])

    outcome = DeckRule().evaluate(_ctx(db, t.id))

    assert {a.code for a in outcome.awards} == {"deck_tron", "deck_elves", "deck_burn"}


def test_collector_counts_distinct_deck_achievements(db, alice, arch_svc):
    for i, name in enumerate(("Tron", "Elves", "Burn")):
        archetype = arch_svc.get_or_create_by_name(name)
        t = _tournament(db, f"Pauper {i}", days_ago=20 - i * 7)
        _register(db, t, alice, archetype)
        _rounds(db, t, "Иванова Алиса", [(2, 0)])

    outcome = CollectorRule().evaluate(_ctx(db, t.id))

    assert [p.value for p in outcome.progress] == [3]
    assert [p.threshold for p in outcome.progress] == [5]


# ── новые ачивки: стойкость, клубы, последний, месть ─────────────────────────


def test_resilient_awarded_for_playing_all_rounds_while_losing(db, alice, archetype_burn):
    t = _tournament(db, "Pauper 1")
    _register(db, t, alice, archetype_burn)
    _rounds(db, t, "Иванова Алиса", [(2, 1), (0, 2), (1, 2), (0, 2)])  # 1-3, но все раунды

    outcome = ResilientRule().evaluate(_ctx(db, t.id))

    assert [a.code for a in outcome.awards] == [Codes.RESILIENT]
    assert "1-3" in outcome.awards[0].evidence


def test_resilient_not_awarded_if_player_dropped(db, alice, archetype_burn):
    """Снялся после двух поражений — это не «отыграл до конца»."""
    t = _tournament(db, "Pauper 1")
    _register(db, t, alice, archetype_burn)
    _rounds(db, t, "Иванова Алиса", [(0, 2), (0, 2)])
    db.add(
        models.RoundPairing(
            tournament_id=t.id,
            round_number=3,
            player_name="Другой Игрок",
            opponent_name="Opp",
            player_wins=2,
            opponent_wins=0,
        )
    )
    db.commit()

    assert ResilientRule().evaluate(_ctx(db, t.id)).awards == []


def test_resilient_not_awarded_for_decent_result(db, alice, archetype_burn):
    t = _tournament(db, "Pauper 1")
    _register(db, t, alice, archetype_burn)
    _rounds(db, t, "Иванова Алиса", [(2, 0), (2, 1), (0, 2), (0, 2)])  # 2-2

    assert ResilientRule().evaluate(_ctx(db, t.id)).awards == []


def test_club_tourist_needs_both_clubs(db, alice, archetype_burn):
    first = _tournament(db, "Goldfish 1", club="Goldfish", days_ago=14)
    _register(db, first, alice, archetype_burn)
    _rounds(db, first, "Иванова Алиса", [(2, 0)])

    assert ClubTouristRule().evaluate(_ctx(db, first.id)).awards == []

    second = _tournament(db, "Edinorog 1", club="Edinorog", days_ago=7)
    _register(db, second, alice, archetype_burn)
    _rounds(db, second, "Иванова Алиса", [(2, 0)])

    outcome = ClubTouristRule().evaluate(_ctx(db, second.id))

    assert [a.code for a in outcome.awards] == [Codes.CLUB_TOURIST]


def test_last_hero_goes_to_the_latest_recorder(db, alice, bob, archetype_burn, archetype_affinity):
    t = _tournament(db, "Pauper 1")
    _register(db, t, alice, archetype_burn)
    _register(db, t, bob, archetype_affinity)
    bob_participant = db.query(models.Participant).filter_by(tournament_id=t.id, user_id=bob.id).one()
    bob_participant.created_at = models.utc_now() + timedelta(hours=1)
    db.commit()
    _rounds(db, t, "Иванова Алиса", [(2, 0)])
    _rounds(db, t, "Петров Боб", [(0, 2)])

    outcome = LastDeckRule().evaluate(_ctx(db, t.id))

    assert [(a.user_id, a.code) for a in outcome.awards] == [(bob.id, Codes.LAST_DECK)]


def _match(db, tournament, player, opponent, pw, ow, rnd=1):
    db.add(
        models.RoundPairing(
            tournament_id=tournament.id,
            round_number=rnd,
            player_name=player,
            opponent_name=opponent,
            player_wins=pw,
            opponent_wins=ow,
        )
    )
    db.commit()


def test_revenge_awarded_after_beating_the_nemesis(db, alice, archetype_burn):
    """Дважды проиграл Петрову, на третий раз выиграл — это месть."""
    for i in range(2):
        past = _tournament(db, f"Pauper {i}", days_ago=30 - i * 7)
        _register(db, past, alice, archetype_burn)
        _match(db, past, "Иванова Алиса", "Петров Боб", 0, 2)

    today = _tournament(db, "Pauper today")
    _register(db, today, alice, archetype_burn)
    _match(db, today, "Иванова Алиса", "Петров Боб", 2, 1)

    outcome = RevengeRule().evaluate(_ctx(db, today.id))

    assert [a.code for a in outcome.awards] == [Codes.REVENGE]
    assert "Петров Боб" in outcome.awards[0].evidence


def test_revenge_needs_a_losing_history(db, alice, archetype_burn):
    """Одна встреча — ещё не «стабильно проигрывал»."""
    past = _tournament(db, "Pauper 1", days_ago=14)
    _register(db, past, alice, archetype_burn)
    _match(db, past, "Иванова Алиса", "Петров Боб", 0, 2)

    today = _tournament(db, "Pauper today")
    _register(db, today, alice, archetype_burn)
    _match(db, today, "Иванова Алиса", "Петров Боб", 2, 0)

    assert RevengeRule().evaluate(_ctx(db, today.id)).awards == []
