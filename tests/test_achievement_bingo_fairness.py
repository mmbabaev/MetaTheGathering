from collections import Counter
from math import isclose, log2

import pytest
from pydantic import ValidationError

from services.achievements.bingo import (
    FAIRNESS_MODEL_VERSION,
    DataSource,
    Difficulty,
    FairnessConstraints,
    FixturePersona,
    WinningLineKind,
    analyze_board_fairness,
    completion_probability_to_weight,
    fixture_candidates,
    generate_board,
    winning_lines,
)


def _neutral_candidates():
    return tuple(
        candidate.model_copy(
            update={
                "difficulty": Difficulty.MEDIUM,
                "data_source": DataSource.DATABASE,
                "requires_high_winrate": False,
            }
        )
        for candidate in fixture_candidates(FixturePersona.PRO)[:16]
    )


def _uniform_overrides(candidates, probability: float = 0.8):
    return {candidate.candidate_id: probability for candidate in candidates}


def test_winning_lines_are_four_rows_four_columns_and_two_diagonals():
    lines = winning_lines()

    assert [line.line_id for line in lines] == [
        "R0",
        "R1",
        "R2",
        "R3",
        "C0",
        "C1",
        "C2",
        "C3",
        "D0",
        "D1",
    ]
    assert Counter(line.kind for line in lines) == {
        WinningLineKind.ROW: 4,
        WinningLineKind.COLUMN: 4,
        WinningLineKind.DIAGONAL: 2,
    }
    assert lines[0].cell_indexes == (0, 1, 2, 3)
    assert lines[4].cell_indexes == (0, 4, 8, 12)
    assert lines[8].cell_indexes == (0, 5, 10, 15)
    assert lines[9].cell_indexes == (3, 6, 9, 12)


def test_diagonal_cells_belong_to_three_lines_and_other_cells_to_two():
    memberships = Counter(index for line in winning_lines() for index in line.cell_indexes)

    assert sum(memberships.values()) == 40
    assert Counter(memberships.values()) == {2: 8, 3: 8}


def test_non_square_geometry_is_rejected():
    with pytest.raises(ValueError, match="square board"):
        winning_lines(rows=4, columns=5)
    with pytest.raises(ValidationError, match="square board"):
        FairnessConstraints(rows=4, columns=5)


@pytest.mark.parametrize(
    "probability, expected",
    [
        (0.95, 0.074),
        (0.80, 0.322),
        (0.50, 1.000),
        (0.25, 2.000),
        (0.10, 3.322),
        (0.05, 4.322),
    ],
)
def test_completion_probability_is_converted_to_additive_bits(probability, expected):
    assert round(completion_probability_to_weight(probability), 3) == expected


def test_probability_weight_clamps_only_for_numerical_weight():
    candidates = _neutral_candidates()
    overrides = _uniform_overrides(candidates)
    overrides[candidates[0].candidate_id] = 1.0

    diagnostics = analyze_board_fairness(candidates, probability_overrides=overrides)
    cell = diagnostics.cells[0]

    assert cell.completion_probability == 1.0
    assert cell.weight_probability == 0.95
    assert cell.probability_clamped is True
    assert isclose(cell.difficulty_weight, -log2(0.95))
    assert diagnostics.balanced is False
    assert any(candidates[0].candidate_id in reason for reason in diagnostics.unsatisfied)


def test_uniform_personal_probabilities_produce_ten_equal_valid_lines():
    candidates = _neutral_candidates()

    diagnostics = analyze_board_fairness(
        candidates,
        probability_overrides=_uniform_overrides(candidates),
    )

    assert diagnostics.fairness_model_version == FAIRNESS_MODEL_VERSION
    assert len(diagnostics.lines) == 10
    assert diagnostics.structurally_valid is True
    assert diagnostics.balanced is True
    assert diagnostics.relative_imbalance == 0.0
    assert diagnostics.probability_ratio == 1.0
    assert all(isclose(line.independent_completion_probability, 0.8**4) for line in diagnostics.lines)
    assert {cell.probability_source for cell in diagnostics.cells} == {"override"}
    assert (
        diagnostics.stable_json()
        == analyze_board_fairness(
            candidates,
            probability_overrides=_uniform_overrides(candidates),
        ).stable_json()
    )


def test_vertical_and_diagonal_constraints_are_not_treated_as_cosmetic():
    candidates = list(_neutral_candidates())
    for index in (0, 4):
        candidates[index] = candidates[index].model_copy(
            update={
                "difficulty": Difficulty.RARE,
                "data_source": DataSource.PEER_CONFIRMATION,
            }
        )

    diagnostics = analyze_board_fairness(
        candidates,
        probability_overrides=_uniform_overrides(candidates),
    )
    by_id = {line.line.line_id: line for line in diagnostics.lines}

    assert by_id["R0"].valid is True
    assert by_id["R1"].valid is True
    assert by_id["C0"].valid is False
    assert by_id["C0"].rare_count == 2
    assert by_id["C0"].peer_confirmed_count == 2
    assert diagnostics.structurally_valid is False
    assert diagnostics.balanced is False
    assert any(reason.startswith("C0:") for reason in diagnostics.unsatisfied)


def test_fixture_attainability_is_explicitly_marked_as_preview_fallback():
    candidates = _neutral_candidates()

    diagnostics = analyze_board_fairness(candidates)

    assert diagnostics.uses_independence_fallback is True
    assert {cell.probability_source for cell in diagnostics.cells} == {"attainability"}


def test_unknown_probability_override_is_rejected_for_auditability():
    with pytest.raises(ValueError, match="unknown candidate_id"):
        analyze_board_fairness(_neutral_candidates(), probability_overrides={"missing": 0.5})


def test_board_shape_and_candidate_ids_are_validated():
    candidates = _neutral_candidates()
    with pytest.raises(ValueError, match="expected 16 candidates"):
        analyze_board_fairness(candidates[:-1])
    with pytest.raises(ValueError, match="unique candidate_id"):
        analyze_board_fairness((*candidates[:-1], candidates[0]))


def test_ineligible_candidate_cannot_be_smuggled_into_fairness_analysis():
    candidates = list(_neutral_candidates())
    candidates[0] = candidates[0].model_copy(
        update={
            "eligibility": candidates[0].eligibility.model_copy(
                update={"eligible": False, "reason_code": "no_baseline"}
            )
        }
    )

    with pytest.raises(ValueError, match="ineligible candidate"):
        analyze_board_fairness(candidates)


@pytest.mark.parametrize("probability", [-0.01, 1.01])
def test_probability_outside_unit_interval_is_rejected(probability):
    with pytest.raises(ValueError, match="between 0 and 1"):
        completion_probability_to_weight(probability)


@pytest.mark.parametrize("probability", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_probability_is_rejected(probability):
    with pytest.raises(ValueError, match="between 0 and 1"):
        completion_probability_to_weight(probability)


@pytest.mark.parametrize("persona", list(FixturePersona))
def test_existing_v1_boards_receive_complete_v2_diagnostics_without_mutation(persona):
    for seed in range(25):
        draft = generate_board(
            fixture_candidates(persona),
            season_id="season-v1-preview",
            player_id=f"fixture-{persona.value}",
            seed=seed,
            catalog_version="fixture-v1",
        )
        candidate_ids_before = [cell.candidate.candidate_id for cell in draft.cells]

        diagnostics = analyze_board_fairness([cell.candidate for cell in draft.cells])

        assert len(diagnostics.lines) == 10
        assert [line.line.line_id for line in diagnostics.lines] == [
            "R0",
            "R1",
            "R2",
            "R3",
            "C0",
            "C1",
            "C2",
            "C3",
            "D0",
            "D1",
        ]
        assert [cell.candidate.candidate_id for cell in draft.cells] == candidate_ids_before
        assert diagnostics.constraints.max_relative_imbalance == 0.10
