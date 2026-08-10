"""Regression contracts for issue #199: eligibility, read-only identity and progress events."""

from datetime import timedelta

from core import models
from core.schemas import TournamentCreate
from services.achievements import AchievementService
from services.achievements.definitions import Codes
from services.achievements.rules import default_rules
from services.tournament import TournamentService


def _tournament(db, title: str, *, status=models.TournamentStatus.CLOSED, days_ago=0):
    created = TournamentService(db).create_tournament(
        TournamentCreate(title=title, chat_id=100 + db.query(models.Tournament).count())
    )
    tournament = db.get(models.Tournament, created.id)
    tournament.started_at = models.utc_now() - timedelta(days=days_ago)
    tournament.status = status
    return tournament


def _register(db, tournament, user, archetype):
    tournament.status = models.TournamentStatus.REGISTRATION
    TournamentService(db).register_participant(
        tournament_id=tournament.id,
        user_id=user.id,
        archetype_id=archetype.id,
        deck_added_by_tg_id=user.tg_id,
    )


def _pair(db, tournament, name: str, *, complete=True):
    db.add(
        models.RoundPairing(
            tournament_id=tournament.id,
            round_number=1,
            player_name=name,
            opponent_name="Opponent",
            player_wins=2 if complete else None,
            opponent_wins=0 if complete else None,
        )
    )
    tournament.status = models.TournamentStatus.CLOSED
    db.commit()


def test_no_show_does_not_move_sport_or_deck_rules(db, user_svc, archetype_burn):
    no_show = user_svc.get_or_create(tg_id=7101, first_name="Нет", last_name="Шоу")
    player = user_svc.get_or_create(tg_id=7102, first_name="Игрок", last_name="Реальный")
    tournament = _tournament(db, "No-show")
    _register(db, tournament, no_show, archetype_burn)
    _register(db, tournament, player, archetype_burn)
    _pair(db, tournament, "Реальный Игрок")

    result = AchievementService(db).process_tournament(tournament.id)

    assert all(item.user_id != no_show.id for item in result.granted)
    assert all(item.user_id != no_show.id for item in result.progress_changes)
    assert any(item.user_id == no_show.id and "не сыграл" in item.reason for item in result.skipped)


def test_ongoing_and_incomplete_history_do_not_move_counters(db, user_svc, archetype_burn, archetype_affinity):
    user = user_svc.get_or_create(tg_id=7201, first_name="Алиса", last_name="История")
    ongoing = _tournament(db, "Ongoing", status=models.TournamentStatus.ONGOING, days_ago=20)
    _register(db, ongoing, user, archetype_burn)
    _pair(db, ongoing, "История Алиса")
    ongoing.status = models.TournamentStatus.ONGOING

    incomplete = _tournament(db, "Incomplete", days_ago=10)
    _register(db, incomplete, user, archetype_burn)
    _pair(db, incomplete, "История Алиса", complete=False)

    current = _tournament(db, "Current", days_ago=1)
    _register(db, current, user, archetype_affinity)
    _pair(db, current, "История Алиса")

    result = AchievementService(db).process_tournament(current.id)
    multiclass = next(item for item in result.progress_changes if item.definition.code == Codes.MULTICLASS)
    assert multiclass.value == 1


def test_preview_does_not_merge_placeholder_users(db, user_svc, archetype_burn):
    real = user_svc.get_or_create(tg_id=7301, first_name="Анна", last_name="Дубль")
    placeholder = models.User(tg_id=-7301, first_name="Анна", last_name="Дубль")
    db.add(placeholder)
    db.commit()
    tournament = _tournament(db, "Identity")
    _register(db, tournament, real, archetype_burn)
    _pair(db, tournament, "Дубль Анна")
    before_ids = {row.id for row in db.query(models.User).all()}

    AchievementService(db).evaluate_for_tournament(tournament.id)

    assert {row.id for row in db.query(models.User).all()} == before_ids
    assert db.get(models.User, placeholder.id) is not None


def test_every_rule_declares_all_independent_requirements():
    for rule in default_rules():
        assert set(rule.requirements.as_dict()) == {
            "self_registered",
            "actually_played",
            "tournament_closed",
            "result_complete",
        }


def test_progress_event_has_audit_evidence_and_replay_is_idempotent(db, user_svc, archetype_burn):
    user = user_svc.get_or_create(tg_id=7401, first_name="Ева", last_name="Аудит")
    tournament = _tournament(db, "Events")
    _register(db, tournament, user, archetype_burn)
    _pair(db, tournament, "Аудит Ева")
    service = AchievementService(db)
    service.process_tournament(tournament.id)
    event = db.query(models.AchievementProgressEvent).filter_by(user_id=user.id).first()

    assert event.before_value == 0 and event.after_value > 0
    assert event.processing_run_id is not None
    assert event.evidence and event.ruleset_version == 1
    assert event.stats_version == "achievement-matches-v1"
    assert event.requirements_json and event.stats_snapshot_json and event.match_ids_json

    progress = db.query(models.UserAchievementProgress).filter_by(user_id=user.id, code=event.code).one()
    db.delete(progress)
    db.commit()
    event_count = db.query(models.AchievementProgressEvent).count()

    assert service.replay_progress_event(event.id).changed is True
    assert service.replay_progress_event(event.id, apply=True).changed is True
    assert service.replay_progress_event(event.id, apply=True).changed is False
    assert db.query(models.AchievementProgressEvent).count() == event_count


def test_owner_override_is_a_separate_immutable_event(db, user_svc):
    user = user_svc.get_or_create(tg_id=7501, first_name="Олег", last_name="Override")

    event = AchievementService(db).override_progress(user.id, Codes.SCRIBE, 7, "ручная сверка owner")

    assert event.event_type == "owner_override"
    assert event.processing_run_id is None
    assert event.before_value == 0 and event.after_value == 7
