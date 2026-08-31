"""Pure fairness analysis for the target bingo-v2 board geometry.

This module deliberately does not change the reproducible bingo-v1 generator.  It
adds the ten-line geometry and the independent-probability weight model needed by
the future personalized solver.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from enum import Enum
from math import isfinite, log2, prod
from statistics import median

from pydantic import Field, model_validator

from services.achievements.bingo.models import (
    DataSource,
    Difficulty,
    FrozenModel,
    InstantiatedCandidate,
    ManifestStatus,
    stable_json,
)

FAIRNESS_MODEL_VERSION = "bingo-v2-fairness-v1"


class WinningLineKind(str, Enum):
    ROW = "row"
    COLUMN = "column"
    DIAGONAL = "diagonal"


class WinningLine(FrozenModel):
    line_id: str = Field(pattern=r"^[RCD][0-9]+$")
    kind: WinningLineKind
    cell_indexes: tuple[int, ...]


class FairnessConstraints(FrozenModel):
    rows: int = Field(default=4, ge=2, le=8)
    columns: int = Field(default=4, ge=2, le=8)
    probability_floor: float = Field(default=0.05, gt=0.0, lt=1.0)
    probability_ceiling: float = Field(default=0.95, gt=0.0, lt=1.0)
    max_relative_imbalance: float = Field(default=0.10, ge=0.0)
    min_accessible_per_line: int = Field(default=1, ge=0)
    max_rare_per_line: int = Field(default=1, ge=0)
    max_peer_confirmed_per_line: int = Field(default=1, ge=0)

    @model_validator(mode="after")
    def validate_fairness_shape(self) -> "FairnessConstraints":
        if self.rows != self.columns:
            raise ValueError("bingo-v2 winning diagonals require a square board")
        if self.probability_floor >= self.probability_ceiling:
            raise ValueError("probability_floor must be lower than probability_ceiling")
        if self.min_accessible_per_line > self.columns:
            raise ValueError("min_accessible_per_line cannot exceed line length")
        return self

    @property
    def cell_count(self) -> int:
        return self.rows * self.columns


class WeightedCellDiagnostic(FrozenModel):
    index: int = Field(ge=0)
    candidate_id: str = Field(min_length=1)
    completion_probability: float = Field(ge=0.0, le=1.0)
    weight_probability: float = Field(gt=0.0, lt=1.0)
    probability_clamped: bool
    difficulty_weight: float = Field(ge=0.0)
    probability_source: str = Field(pattern=r"^(attainability|override)$")


class LineDiagnostic(FrozenModel):
    line: WinningLine
    sum_weight: float = Field(ge=0.0)
    independent_completion_probability: float = Field(ge=0.0, le=1.0)
    accessible_count: int = Field(ge=0)
    rare_count: int = Field(ge=0)
    peer_confirmed_count: int = Field(ge=0)
    difficulty_counts: dict[Difficulty, int]
    valid: bool
    violations: tuple[str, ...] = ()


class FairnessDiagnostics(FrozenModel):
    fairness_model_version: str = FAIRNESS_MODEL_VERSION
    rows: int = Field(ge=2)
    columns: int = Field(ge=2)
    constraints: FairnessConstraints
    cells: tuple[WeightedCellDiagnostic, ...]
    lines: tuple[LineDiagnostic, ...]
    median_line_weight: float = Field(ge=0.0)
    relative_imbalance: float = Field(ge=0.0)
    probability_ratio: float = Field(ge=1.0)
    structurally_valid: bool
    balanced: bool
    uses_independence_fallback: bool = True
    unsatisfied: tuple[str, ...] = ()

    def stable_json(self) -> str:
        return stable_json(self.model_dump(mode="json"))


def winning_lines(*, rows: int = 4, columns: int = 4) -> tuple[WinningLine, ...]:
    """Return rows, columns and both diagonals in stable claim/diagnostic order."""

    if rows != columns:
        raise ValueError("bingo-v2 winning diagonals require a square board")
    if rows < 2:
        raise ValueError("bingo board must be at least 2x2")

    result = [
        WinningLine(
            line_id=f"R{row}",
            kind=WinningLineKind.ROW,
            cell_indexes=tuple(row * columns + column for column in range(columns)),
        )
        for row in range(rows)
    ]
    result.extend(
        WinningLine(
            line_id=f"C{column}",
            kind=WinningLineKind.COLUMN,
            cell_indexes=tuple(row * columns + column for row in range(rows)),
        )
        for column in range(columns)
    )
    result.extend(
        (
            WinningLine(
                line_id="D0",
                kind=WinningLineKind.DIAGONAL,
                cell_indexes=tuple(index * columns + index for index in range(rows)),
            ),
            WinningLine(
                line_id="D1",
                kind=WinningLineKind.DIAGONAL,
                cell_indexes=tuple(index * columns + (columns - index - 1) for index in range(rows)),
            ),
        )
    )
    return tuple(result)


def completion_probability_to_weight(
    probability: float,
    *,
    floor: float = 0.05,
    ceiling: float = 0.95,
) -> float:
    """Convert completion probability to additive bits of difficulty."""

    if not isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise ValueError("completion probability must be between 0 and 1")
    if not 0.0 < floor < ceiling < 1.0:
        raise ValueError("probability bounds must satisfy 0 < floor < ceiling < 1")
    safe_probability = min(max(probability, floor), ceiling)
    return -log2(safe_probability)


def analyze_board_fairness(
    candidates: Sequence[InstantiatedCandidate],
    *,
    probability_overrides: Mapping[str, float] | None = None,
    constraints: FairnessConstraints | None = None,
) -> FairnessDiagnostics:
    """Analyze one already-arranged board across all ten bingo-v2 winning lines.

    The current fixture ``attainability`` is used only as an explicit preview
    fallback.  A future estimator supplies frozen player-specific probabilities via
    ``probability_overrides`` without changing the candidate or bingo-v1 contracts.
    """

    constraints = constraints or FairnessConstraints()
    if len(candidates) != constraints.cell_count:
        raise ValueError(f"expected {constraints.cell_count} candidates, got {len(candidates)}")

    candidate_ids = [candidate.candidate_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("board candidates must have unique candidate_id values")
    ready_statuses = {ManifestStatus.READY_FOR_PREVIEW, ManifestStatus.READY_FOR_SEASON}
    invalid_candidates = [
        candidate.candidate_id
        for candidate in candidates
        if not candidate.eligibility.eligible or candidate.status not in ready_statuses
    ]
    if invalid_candidates:
        raise ValueError(f"board contains ineligible candidate: {', '.join(sorted(invalid_candidates))}")

    overrides = dict(probability_overrides or {})
    unknown_overrides = sorted(set(overrides) - set(candidate_ids))
    if unknown_overrides:
        raise ValueError(f"probability override has unknown candidate_id: {', '.join(unknown_overrides)}")

    weighted_cells: list[WeightedCellDiagnostic] = []
    for index, candidate in enumerate(candidates):
        source = "override" if candidate.candidate_id in overrides else "attainability"
        probability = overrides.get(candidate.candidate_id, candidate.attainability)
        safe_probability = min(
            max(probability, constraints.probability_floor),
            constraints.probability_ceiling,
        )
        weight = completion_probability_to_weight(
            probability,
            floor=constraints.probability_floor,
            ceiling=constraints.probability_ceiling,
        )
        weighted_cells.append(
            WeightedCellDiagnostic(
                index=index,
                candidate_id=candidate.candidate_id,
                completion_probability=probability,
                weight_probability=safe_probability,
                probability_clamped=probability != safe_probability,
                difficulty_weight=weight,
                probability_source=source,
            )
        )

    line_diagnostics = tuple(
        _line_diagnostic(line, candidates, weighted_cells, constraints)
        for line in winning_lines(rows=constraints.rows, columns=constraints.columns)
    )
    line_weights = [line.sum_weight for line in line_diagnostics]
    median_weight = median(line_weights)
    relative_imbalance = (max(line_weights) - min(line_weights)) / median_weight if median_weight else 0.0
    probability_ratio = 2 ** (max(line_weights) - min(line_weights))
    structurally_valid = all(line.valid for line in line_diagnostics)
    has_clamped_probability = any(cell.probability_clamped for cell in weighted_cells)
    balanced = (
        structurally_valid and not has_clamped_probability and relative_imbalance <= constraints.max_relative_imbalance
    )

    unsatisfied = [f"{line.line.line_id}: {violation}" for line in line_diagnostics for violation in line.violations]
    if relative_imbalance > constraints.max_relative_imbalance:
        unsatisfied.append(
            f"relative imbalance {relative_imbalance:.6f} exceeds {constraints.max_relative_imbalance:.6f}"
        )
    for cell in weighted_cells:
        if cell.probability_clamped:
            unsatisfied.append(
                f"{cell.candidate_id}: completion probability {cell.completion_probability:.6f} "
                f"outside [{constraints.probability_floor:.6f}, {constraints.probability_ceiling:.6f}]"
            )

    return FairnessDiagnostics(
        rows=constraints.rows,
        columns=constraints.columns,
        constraints=constraints,
        cells=tuple(weighted_cells),
        lines=line_diagnostics,
        median_line_weight=median_weight,
        relative_imbalance=relative_imbalance,
        probability_ratio=probability_ratio,
        structurally_valid=structurally_valid,
        balanced=balanced,
        unsatisfied=tuple(unsatisfied),
    )


def _line_diagnostic(
    line: WinningLine,
    candidates: Sequence[InstantiatedCandidate],
    cells: Sequence[WeightedCellDiagnostic],
    constraints: FairnessConstraints,
) -> LineDiagnostic:
    line_candidates = [candidates[index] for index in line.cell_indexes]
    line_cells = [cells[index] for index in line.cell_indexes]
    accessible_count = sum(not candidate.requires_high_winrate for candidate in line_candidates)
    rare_count = sum(candidate.difficulty == Difficulty.RARE for candidate in line_candidates)
    peer_count = sum(candidate.data_source == DataSource.PEER_CONFIRMATION for candidate in line_candidates)
    violations: list[str] = []
    if accessible_count < constraints.min_accessible_per_line:
        violations.append(f"needs {constraints.min_accessible_per_line} accessible cells, got {accessible_count}")
    if rare_count > constraints.max_rare_per_line:
        violations.append(f"allows {constraints.max_rare_per_line} rare cells, got {rare_count}")
    if peer_count > constraints.max_peer_confirmed_per_line:
        violations.append(f"allows {constraints.max_peer_confirmed_per_line} peer-confirmed cells, got {peer_count}")

    sum_weight = sum(cell.difficulty_weight for cell in line_cells)
    independent_probability = prod(2**-cell.difficulty_weight for cell in line_cells)
    difficulty_counts = Counter(candidate.difficulty for candidate in line_candidates)
    return LineDiagnostic(
        line=line,
        sum_weight=sum_weight,
        independent_completion_probability=independent_probability,
        accessible_count=accessible_count,
        rare_count=rare_count,
        peer_confirmed_count=peer_count,
        difficulty_counts={difficulty: difficulty_counts[difficulty] for difficulty in Difficulty},
        valid=not violations,
        violations=tuple(violations),
    )
