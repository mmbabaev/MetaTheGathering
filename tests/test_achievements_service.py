"""Движок ачивок: идемпотентность выдачи, дельта прогресса, полка игрока и отчёт."""

from datetime import timedelta

import pytest

from core import models
from core.schemas import TournamentCreate
from services.achievements import AchievementService, build_report
from services.achievements.definitions import Codes
from services.tournament import TournamentService


def _tournament(db, title, *, club="Goldfish", days_ago=0):
    svc = TournamentService(db)
    active = (
        db.query(models.Tournament)
        .filter(models.Tournament.chat_id == 100, models.Tournament.status != models.TournamentStatus.CLOSED)
        .first()
    )
    if active is not None:
        svc.close_tournament(active.id)
    created = svc.create_tournament(TournamentCreate(title=title, chat_id=100))
    t = db.get(models.Tournament, created.id)
    t.club = club
    t.started_at = models.utc_now() - timedelta(days=days_ago)
    db.commit()
    return t


def _play(db, tournament, user, archetype, results, *, name):
    TournamentService(db).register_participant(
        tournament_id=tournament.id,
        user_id=user.id,
        archetype_id=archetype.id,
        deck_added_by_tg_id=user.tg_id,
    )
    for i, (pw, ow) in enumerate(results, start=1):
        db.add(
            models.RoundPairing(
                tournament_id=tournament.id,
                round_number=i,
                player_name=name,
                opponent_name=f"Opp{i}",
                table_number=i,
                player_wins=pw,
                opponent_wins=ow,
            )
        )
    db.commit()


@pytest.fixture
def alice(user_svc):
    return user_svc.get_or_create(tg_id=5001, first_name="Алиса", last_name="Иванова")


def test_process_tournament_grants_and_is_idempotent(db, alice, archetype_burn):
    t = _tournament(db, "Pauper 1")
    _play(db, t, alice, archetype_burn, [(2, 0), (2, 0)], name="Иванова Алиса")
    svc = AchievementService(db)

    first = svc.process_tournament(t.id)
    second = svc.process_tournament(t.id)

    assert {g.definition.code for g in first.granted} == {Codes.DEBUT, Codes.UNDEFEATED, Codes.FIRST_DECK}
    assert second.granted == [] and second.progress_changes == []
    assert db.query(models.UserAchievement).count() == len(first.granted)


def test_progress_change_reports_delta_not_absolute(db, alice, archetype_burn, archetype_affinity):
    first = _tournament(db, "Pauper 1", days_ago=14)
    _play(db, first, alice, archetype_burn, [(2, 0)], name="Иванова Алиса")
    svc = AchievementService(db)
    svc.process_tournament(first.id)

    second = _tournament(db, "Pauper 2", days_ago=7)
    _play(db, second, alice, archetype_affinity, [(2, 0)], name="Иванова Алиса")
    result = svc.process_tournament(second.id)

    multiclass = [c for c in result.progress_changes if c.definition.code == Codes.MULTICLASS]
    assert (multiclass[0].previous, multiclass[0].value, multiclass[0].delta) == (1, 2, 1)


def test_incomplete_tournament_is_not_processed(db, alice, archetype_burn):
    t = _tournament(db, "Pauper 1")
    _play(db, t, alice, archetype_burn, [(None, None)], name="Иванова Алиса")

    assert AchievementService(db).process_tournament(t.id) is None


def test_placeholder_user_gets_nothing(db, user_svc, archetype_burn):
    ghost, _ = user_svc.get_or_create_by_name("Призрак", "Импортный")
    t = _tournament(db, "Pauper 1")
    _play(db, t, ghost, archetype_burn, [(2, 0)], name="Импортный Призрак")

    result = AchievementService(db).process_tournament(t.id)

    assert result.granted == []
    assert [s.reason for s in result.skipped] == ["нет аккаунта в боте"]


def test_shelf_shows_unlocked_and_progress(db, alice, archetype_burn):
    t = _tournament(db, "Pauper 1")
    _play(db, t, alice, archetype_burn, [(2, 0), (2, 0)], name="Иванова Алиса")
    svc = AchievementService(db)
    svc.process_tournament(t.id)

    views = svc.list_for_user(alice.id)
    unlocked = {v.definition.code for v in views if v.unlocked}
    progress = {v.definition.code: v.progress for v in views if not v.unlocked and v.progress}

    assert Codes.DEBUT in unlocked
    assert progress[Codes.REGULAR] == 1  # серия из одного турнира — до «Завсегдатая I» ещё далеко


def test_report_lists_awards_progress_and_skipped(db, alice, user_svc, archetype_burn, archetype_affinity):
    t = _tournament(db, "Pauper 1")
    _play(db, t, alice, archetype_burn, [(2, 0), (2, 0)], name="Иванова Алиса")
    lazy = user_svc.get_or_create(tg_id=5002, first_name="Боб", last_name="Петров")
    TournamentService(db).register_participant(tournament_id=t.id, user_id=lazy.id)

    result = AchievementService(db).process_tournament(t.id)
    messages = build_report(result)

    assert len(messages) == 1
    text = messages[0]
    assert "НОВЫЕ АЧИВКИ" in text and "Дебют" in text
    assert "НЕ В ЗАЧЁТ" in text and "Петров Боб — колода не записана" in text


def test_report_is_empty_when_nothing_changed(db, alice, archetype_burn):
    t = _tournament(db, "Pauper 1")
    _play(db, t, alice, archetype_burn, [(2, 0)], name="Иванова Алиса")
    svc = AchievementService(db)
    svc.process_tournament(t.id)

    assert build_report(svc.process_tournament(t.id)) == []


def test_long_report_is_split_into_several_messages(db, user_svc, archetype_burn):
    t = _tournament(db, "Pauper 1")
    for i in range(60):
        player = user_svc.get_or_create(tg_id=6000 + i, first_name=f"Игрок{i}", last_name="Длиннофамильный")
        _play(db, t, player, archetype_burn, [(2, 0)], name=f"Длиннофамильный Игрок{i}")

    messages = build_report(AchievementService(db).process_tournament(t.id))

    assert len(messages) > 1
    assert all(len(m) <= 4096 for m in messages)
