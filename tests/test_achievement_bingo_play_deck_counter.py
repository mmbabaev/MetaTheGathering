from datetime import datetime, timedelta, timezone

import pytest

from services.achievements.bingo import (
    FIXTURE_DECK_TARGETS,
    PLAY_DECK_CODE,
    PLAY_DECK_COUNTER_COMPLETION_KEY,
    PLAY_DECK_COUNTER_MANIFEST_VERSION,
    PLAY_DECK_COUNTER_PARAMETERIZER_KEY,
    PLAY_DECK_COUNTER_PROGRESS_KEY,
    PLAY_DECK_TARGET_PARAM,
    PLAY_DECK_TARGET_TOURNAMENTS,
    PREVIEW_MANIFESTS,
    PlayDeckTournamentEvidence,
    build_play_deck_counter_manifest,
    evaluate_play_deck_counter,
    instantiate_play_deck_candidates,
    instantiate_play_deck_counter_candidates,
)

ACTIVATED_AT = datetime(2026, 9, 1, 12, 0)


def _base_manifest():
    return next(item for item in PREVIEW_MANIFESTS if item.code == PLAY_DECK_CODE)


def _counter_candidate():
    manifest = build_play_deck_counter_manifest(_base_manifest())
    return instantiate_play_deck_counter_candidates(
        manifest,
        FIXTURE_DECK_TARGETS[:1],
        stats_snapshot_id="snapshot-2026-09-01",
        attainability=0.35,
    )[0]


def _evidence(
    tournament_id: int,
    *,
    day: int,
    deck_general_name: str | None = "Blue Terror",
    self_registered: bool = True,
    actually_played: bool = True,
    tournament_closed: bool = True,
    result_complete: bool = True,
) -> PlayDeckTournamentEvidence:
    return PlayDeckTournamentEvidence(
        tournament_id=tournament_id,
        played_at=ACTIVATED_AT + timedelta(days=day),
        deck_general_name=deck_general_name,
        self_registered=self_registered,
        actually_played=actually_played,
        tournament_closed=tournament_closed,
        result_complete=result_complete,
    )


def test_counter_manifest_and_candidate_freeze_v2_contract():
    base = _base_manifest()
    manifest = build_play_deck_counter_manifest(base)

    candidate = instantiate_play_deck_counter_candidates(
        manifest,
        FIXTURE_DECK_TARGETS[:1],
        stats_snapshot_id="snapshot-2026-09-01",
        attainability=0.35,
    )[0]

    assert manifest.version == PLAY_DECK_COUNTER_MANIFEST_VERSION
    assert manifest.parameterizer_key == PLAY_DECK_COUNTER_PARAMETERIZER_KEY
    assert manifest.progress_evaluator_key == PLAY_DECK_COUNTER_PROGRESS_KEY
    assert manifest.completion_evaluator_key == PLAY_DECK_COUNTER_COMPLETION_KEY
    assert candidate.candidate_id.endswith(":v2")
    assert candidate.hint == "Сыграй 3 турнира на колоде Blue Terror"
    assert candidate.frozen_params[PLAY_DECK_TARGET_PARAM] == PLAY_DECK_TARGET_TOURNAMENTS
    assert candidate.attainability == 0.35
    assert {
        "played_at",
        "self_registered",
        "actually_played",
        "tournament_closed",
        "result_complete",
    }.issubset(candidate.evidence_fields)


def test_binary_v1_candidate_remains_unchanged():
    base = _base_manifest()

    candidate = instantiate_play_deck_candidates(
        base,
        FIXTURE_DECK_TARGETS[:1],
        stats_snapshot_id="snapshot-2026-09-01",
    )[0]

    assert candidate.candidate_id.endswith(":v1")
    assert candidate.hint == "Сыграй турнир на колоде Blue Terror"
    assert candidate.progress_evaluator_key == "play_deck_binary_progress_v1"
    assert PLAY_DECK_TARGET_PARAM not in candidate.frozen_params


def test_counter_completes_on_three_distinct_post_activation_tournaments():
    candidate = _counter_candidate()

    progress = evaluate_play_deck_counter(
        candidate,
        [_evidence(103, day=3), _evidence(101, day=1), _evidence(102, day=2)],
        activated_at=ACTIVATED_AT,
    )

    assert progress.current == 3
    assert progress.target == 3
    assert progress.completed is True
    assert progress.counted_tournament_ids == (101, 102, 103)
    assert progress.completed_at == ACTIVATED_AT + timedelta(days=3)


def test_counter_is_idempotent_and_caps_evidence_at_frozen_target():
    candidate = _counter_candidate()
    first = _evidence(101, day=1)
    history = [first, _evidence(104, day=4), _evidence(103, day=3), first, _evidence(102, day=2)]

    progress = evaluate_play_deck_counter(candidate, history, activated_at=ACTIVATED_AT)
    replay = evaluate_play_deck_counter(candidate, list(reversed(history)), activated_at=ACTIVATED_AT)

    assert progress == replay
    assert progress.current == 3
    assert progress.counted_tournament_ids == (101, 102, 103)
    assert 104 not in progress.counted_tournament_ids


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("self_registered", False),
        ("actually_played", False),
        ("tournament_closed", False),
        ("result_complete", False),
        ("deck_general_name", None),
        ("deck_general_name", "Grixis Affinity"),
    ],
)
def test_counter_rejects_evidence_that_does_not_pass_every_gate(override: str, value: object):
    candidate = _counter_candidate()
    kwargs = {override: value}

    progress = evaluate_play_deck_counter(
        candidate,
        [_evidence(101, day=1, **kwargs)],
        activated_at=ACTIVATED_AT,
    )

    assert progress.current == 0
    assert progress.completed is False
    assert progress.counted_tournament_ids == ()
    assert progress.completed_at is None


def test_counter_uses_activation_boundary_and_canonical_general_name():
    candidate = _counter_candidate()

    progress = evaluate_play_deck_counter(
        candidate,
        [
            _evidence(100, day=-1),
            _evidence(101, day=0, deck_general_name="  BLUE   terror "),
        ],
        activated_at=ACTIVATED_AT,
    )

    assert progress.current == 1
    assert progress.counted_tournament_ids == (101,)


def test_counter_normalizes_aware_datetimes_to_utc():
    candidate = _counter_candidate()
    moscow = timezone(timedelta(hours=3))
    evidence = _evidence(101, day=0).model_copy(update={"played_at": datetime(2026, 9, 1, 15, 0, tzinfo=moscow)})

    progress = evaluate_play_deck_counter(
        candidate,
        [evidence],
        activated_at=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
    )

    assert progress.current == 1
    assert progress.counted_tournament_ids == (101,)


def test_counter_rejects_conflicting_rows_for_one_tournament():
    candidate = _counter_candidate()

    with pytest.raises(ValueError, match="conflicting evidence for tournament 101"):
        evaluate_play_deck_counter(
            candidate,
            [_evidence(101, day=1), _evidence(101, day=1, result_complete=False)],
            activated_at=ACTIVATED_AT,
        )


def test_counter_rejects_v1_candidate_and_mutated_frozen_target():
    base = _base_manifest()
    v1_candidate = instantiate_play_deck_candidates(
        base,
        FIXTURE_DECK_TARGETS[:1],
        stats_snapshot_id="snapshot-2026-09-01",
    )[0]
    invalid_target = _counter_candidate().model_copy(
        update={"frozen_params": {"deckGeneralName": "Blue Terror", PLAY_DECK_TARGET_PARAM: True}}
    )

    with pytest.raises(ValueError, match="counter-v2 contract"):
        evaluate_play_deck_counter(v1_candidate, [], activated_at=ACTIVATED_AT)
    with pytest.raises(ValueError, match="must freeze targetTournaments=3"):
        evaluate_play_deck_counter(invalid_target, [], activated_at=ACTIVATED_AT)
