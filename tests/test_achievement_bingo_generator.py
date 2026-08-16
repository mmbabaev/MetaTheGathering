"""Contracts and broad-seed fairness checks for the pure Board Lab generator."""

from collections import Counter

import pytest
from pydantic import ValidationError

from services.achievements.bingo import (
    FIXTURE_CATALOG_VERSION,
    PREVIEW_MANIFESTS,
    BoardConstraints,
    BoardGenerationError,
    DataSource,
    Difficulty,
    EligibilityResult,
    FixturePersona,
    fixture_candidates,
    generate_board,
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
