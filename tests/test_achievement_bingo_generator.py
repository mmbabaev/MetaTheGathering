"""Contracts and broad-seed fairness checks for the pure Board Lab generator."""

from collections import Counter

import pytest
from pydantic import ValidationError

from services.achievements.bingo import (
    FIXTURE_CATALOG_VERSION,
    FIXTURE_DECK_STATS_SNAPSHOT_ID,
    FIXTURE_DECK_TARGETS,
    PLAY_DECK_CODE,
    PREVIEW_MANIFESTS,
    BoardConstraints,
    BoardGenerationError,
    DataSource,
    Difficulty,
    EligibilityResult,
    FixturePersona,
    fixture_candidates,
    generate_board,
    instantiate_play_deck_candidates,
    play_deck_completed,
)


def _generate(persona: FixturePersona, seed: int, candidates=None):
    return generate_board(
        candidates or fixture_candidates(persona),
        season_id="season-2026-01",
        player_id=f"fixture-{persona.value}",
        seed=seed,
        catalog_version=FIXTURE_CATALOG_VERSION,
    )


def test_preview_catalog_has_versioned_diverse_candidates():
    codes = {manifest.code for manifest in PREVIEW_MANIFESTS}

    assert len(PREVIEW_MANIFESTS) >= 20
    assert len(codes) == len(PREVIEW_MANIFESTS)
    assert set(Difficulty) == {manifest.difficulty for manifest in PREVIEW_MANIFESTS}
    assert {manifest.data_source for manifest in PREVIEW_MANIFESTS} == set(DataSource)
    assert all(manifest.version >= 1 for manifest in PREVIEW_MANIFESTS)
    assert all(manifest.parameterizer_key for manifest in PREVIEW_MANIFESTS)
    assert all(manifest.progress_evaluator_key for manifest in PREVIEW_MANIFESTS)
    assert all(manifest.completion_evaluator_key for manifest in PREVIEW_MANIFESTS)
    assert all(manifest.evidence_fields for manifest in PREVIEW_MANIFESTS)
    assert all(fallback in codes for manifest in PREVIEW_MANIFESTS for fallback in manifest.fallback_codes)


def test_play_deck_x_is_parameterized_from_frozen_general_names():
    manifest = next(item for item in PREVIEW_MANIFESTS if item.code == PLAY_DECK_CODE)

    candidates = instantiate_play_deck_candidates(
        manifest,
        FIXTURE_DECK_TARGETS[:2],
        stats_snapshot_id="snapshot-2026-09-01",
    )

    assert len(candidates) == 2
    assert len({candidate.candidate_id for candidate in candidates}) == 2
    assert {candidate.mechanic_key for candidate in candidates} == {PLAY_DECK_CODE}
    assert [candidate.frozen_params["deckGeneralName"] for candidate in candidates] == [
        "Blue Terror",
        "Grixis Affinity",
    ]
    assert candidates[0].title == "Хитрый уж"
    assert candidates[0].hint == "Сыграй турнир на колоде Blue Terror"
    assert candidates[0].frozen_params["statsSnapshotId"] == "snapshot-2026-09-01"
    assert "deck_general_name" in candidates[0].evidence_fields
    assert candidates[0].parameterizer_key == "play_deck_from_frozen_catalog_v1"
    assert candidates[0].completion_evaluator_key == "play_deck_completed_v1"


def test_play_deck_x_completion_uses_frozen_canonical_name():
    manifest = next(item for item in PREVIEW_MANIFESTS if item.code == PLAY_DECK_CODE)
    candidate = instantiate_play_deck_candidates(
        manifest,
        FIXTURE_DECK_TARGETS[:1],
        stats_snapshot_id="snapshot-2026-09-01",
    )[0]

    assert play_deck_completed(candidate, "  blue   TERROR ") is True
    assert play_deck_completed(candidate, "Mono Blue") is False
    assert play_deck_completed(candidate, None) is False


def test_play_deck_x_rejects_duplicate_canonical_targets():
    manifest = next(item for item in PREVIEW_MANIFESTS if item.code == PLAY_DECK_CODE)
    duplicate = FIXTURE_DECK_TARGETS[0].__class__(
        " blue  terror ",
        "Ещё один заголовок",
        rank=2,
        participations=10,
        players=5,
    )

    with pytest.raises(ValueError, match="unique general_name"):
        instantiate_play_deck_candidates(
            manifest,
            (FIXTURE_DECK_TARGETS[0], duplicate),
            stats_snapshot_id="snapshot-2026-09-01",
        )


def test_play_deck_x_without_frozen_targets_is_auditable_rejection():
    manifest = next(item for item in PREVIEW_MANIFESTS if item.code == PLAY_DECK_CODE)

    candidate = instantiate_play_deck_candidates(
        manifest,
        (),
        stats_snapshot_id="empty-snapshot-2026-09-01",
    )[0]

    assert candidate.eligibility.eligible is False
    assert candidate.eligibility.reason_code == "no_frozen_deck_targets"
    assert candidate.fallback_codes == ("try_new_deck",)


def test_generated_board_can_contain_one_concrete_play_deck_x_cell():
    draft = _generate(FixturePersona.REGULAR, 0)
    play_deck_cells = [cell.candidate for cell in draft.cells if cell.candidate.manifest_code == PLAY_DECK_CODE]

    assert len(play_deck_cells) == 1
    assert play_deck_cells[0].title in {target.title for target in FIXTURE_DECK_TARGETS}
    assert play_deck_cells[0].frozen_params["deckGeneralName"] in {
        target.general_name for target in FIXTURE_DECK_TARGETS
    }
    assert play_deck_cells[0].frozen_params["statsSnapshotId"] == FIXTURE_DECK_STATS_SNAPSHOT_ID


def test_preview_play_deck_targets_match_current_top_three_snapshot():
    assert FIXTURE_CATALOG_VERSION == "board-lab-fixtures-v3"
    assert FIXTURE_DECK_STATS_SNAPSHOT_ID == "fixture-stats-2026-08-19-365d"
    assert [
        (target.general_name, target.title, target.rank, target.participations, target.players)
        for target in FIXTURE_DECK_TARGETS
    ] == [
        ("Blue Terror", "Хитрый уж", 1, 46, 27),
        ("Grixis Affinity", "Родство с металлом", 2, 36, 20),
        ("Jund Midrange", "Мосты не горят", 3, 29, 15),
    ]


def test_ineligible_candidate_requires_auditable_reason():
    with pytest.raises(ValidationError, match="reason_code"):
        EligibilityResult(eligible=False)


@pytest.mark.parametrize("persona", list(FixturePersona))
def test_one_hundred_seeds_satisfy_board_and_row_constraints(persona):
    for seed in range(100):
        draft = _generate(persona, seed)
        candidates = [cell.candidate for cell in draft.cells]

        assert len(candidates) == 16
        assert Counter(candidate.difficulty for candidate in candidates) == Counter(
            BoardConstraints().difficulty_quotas
        )
        assert len({candidate.candidate_id for candidate in candidates}) == 16
        assert len({candidate.mechanic_key for candidate in candidates}) == 16
        assert sum(candidate.manifest_code == PLAY_DECK_CODE for candidate in candidates) <= 1
        assert len({candidate.category for candidate in candidates}) >= 4
        assert all(row.valid for row in draft.diagnostics.rows)
        assert all(row.easy_count >= 1 for row in draft.diagnostics.rows)
        assert all(row.rare_count <= 1 for row in draft.diagnostics.rows)
        assert all(row.accessible_count >= 1 for row in draft.diagnostics.rows)
        assert all(row.peer_confirmed_count <= 1 for row in draft.diagnostics.rows)
        assert sum(candidate.data_source == DataSource.PEER_CONFIRMATION for candidate in candidates) <= 2
        opponents = [
            candidate.target_opponent_id for candidate in candidates if candidate.target_opponent_id is not None
        ]
        assert len(opponents) == len(set(opponents))


def test_same_input_is_byte_for_byte_deterministic_and_order_independent():
    candidates = fixture_candidates(FixturePersona.REGULAR)

    first = _generate(FixturePersona.REGULAR, 42, candidates)
    repeated = _generate(FixturePersona.REGULAR, 42, tuple(reversed(candidates)))

    assert first.stable_json() == repeated.stable_json()
    assert first.input.candidate_fingerprint == repeated.input.candidate_fingerprint


def test_seed_changes_board_but_preserves_constraints():
    first = _generate(FixturePersona.AMATEUR, 1)
    second = _generate(FixturePersona.AMATEUR, 2)

    assert [cell.candidate.candidate_id for cell in first.cells] != [
        cell.candidate.candidate_id for cell in second.cells
    ]
    assert all(row.valid for row in first.diagnostics.rows)
    assert all(row.valid for row in second.diagnostics.rows)


def test_no_data_candidates_are_rejected_with_fallbacks_instead_of_becoming_zero_progress():
    draft = _generate(FixturePersona.NEWCOMER, 7)
    selected_ids = {cell.candidate.candidate_id for cell in draft.cells}
    rejected = draft.diagnostics.rejected_candidates

    assert rejected
    assert all(item.reason_code == "insufficient_h2h_baseline" for item in rejected)
    assert all(item.candidate_id not in selected_ids for item in rejected)
    assert any(item.fallback_codes for item in rejected)
    assert all(cell.candidate.eligibility.eligible for cell in draft.cells)


def test_impossible_pool_returns_actionable_diagnostics_without_rerolling():
    easy_only = tuple(
        candidate for candidate in fixture_candidates(FixturePersona.PRO) if candidate.difficulty == Difficulty.EASY
    )

    with pytest.raises(BoardGenerationError) as raised:
        _generate(FixturePersona.PRO, 1, easy_only)

    assert "need 16 eligible candidates" in str(raised.value)
    assert any("medium" in reason for reason in raised.value.diagnostics.unsatisfied)
    assert raised.value.diagnostics.attempted_assignments == 0


def test_duplicate_candidate_ids_are_rejected_before_search():
    candidates = fixture_candidates(FixturePersona.PRO)

    with pytest.raises(ValueError, match="duplicate candidate_id"):
        _generate(FixturePersona.PRO, 1, (*candidates, candidates[0]))
