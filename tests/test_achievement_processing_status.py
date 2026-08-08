"""Статусы completed/partial/failed и DB-аудит прогонов правил."""

import json

import pytest

from core import models
from services.achievements import AchievementService, build_report
from services.achievements.rules import RuleOutcome


class SuccessfulRule:
    code = "successful"

    def evaluate(self, _ctx):
        return RuleOutcome()


class FailingRule:
    code = "broken"

    def evaluate(self, _ctx):
        raise ValueError("sensitive exception details")


@pytest.fixture
def complete_tournament(db, tournament):
    db.add(
        models.RoundPairing(
            tournament_id=tournament.id,
            round_number=1,
            player_name="Игрок",
            opponent_name="Оппонент",
            player_wins=2,
            opponent_wins=0,
        )
    )
    db.commit()
    return tournament


@pytest.mark.parametrize(
    ("rules", "expected_status", "failed"),
    [
        ([SuccessfulRule()], "completed", 0),
        ([SuccessfulRule(), FailingRule()], "partial", 1),
        ([FailingRule()], "failed", 1),
    ],
)
def test_processing_status_is_persisted(db, complete_tournament, rules, expected_status, failed):
    result = AchievementService(db, rules=rules).process_tournament(complete_tournament.id)

    assert result.status == expected_status
    run = db.query(models.AchievementProcessingRun).one()
    assert run.id == result.processing_run_id
    assert run.status == expected_status
    assert run.rules_total == len(rules)
    assert run.rules_failed == failed
    assert run.completed_at >= run.started_at


def test_failed_run_produces_owner_warning_without_exception_message(db, complete_tournament):
    result = AchievementService(db, rules=[FailingRule()]).process_tournament(complete_tournament.id)

    messages = build_report(result)
    run = db.query(models.AchievementProcessingRun).one()

    assert len(messages) == 1
    assert "⚠️ ОШИБКИ РАСЧЁТА" in messages[0]
    assert "broken — ValueError" in messages[0]
    assert "sensitive exception details" not in messages[0]
    assert json.loads(run.rule_errors_json) == [{"code": "broken", "error_type": "ValueError"}]
    assert "sensitive exception details" not in run.rule_errors_json
