"""Deterministic constraint solver for 4x4 seasonal bingo previews."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable

from services.achievements.bingo.models import (
    ALGORITHM_VERSION,
    BoardCell,
    BoardConstraints,
    BoardDiagnostics,
    BoardDraft,
    Category,
    DataSource,
    Difficulty,
    GenerationInput,
    InstantiatedCandidate,
    ManifestStatus,
    RejectedCandidate,
    RowDiagnostic,
    candidate_fingerprint,
)


class BoardGenerationError(ValueError):
    """The candidate pool cannot satisfy the declared constraints."""

    def __init__(self, diagnostics: BoardDiagnostics) -> None:
        self.diagnostics = diagnostics
        details = "; ".join(diagnostics.unsatisfied) or "unknown constraint conflict"
        super().__init__(f"cannot generate bingo board: {details}")


@dataclass
class _SearchStats:
    attempted_assignments: int = 0
    backtracks: int = 0


def generate_board(
    candidates: Iterable[InstantiatedCandidate],
    *,
    season_id: str,
    player_id: str,
    seed: int,
    constraints: BoardConstraints | None = None,
    algorithm_version: str = ALGORITHM_VERSION,
    catalog_version: str = "preview-v1",
) -> BoardDraft:
    """Build a board without DB access, writes, external calls or unbounded rerolls.

    Candidate order is normalized before search.  For a fixed input, the SHA-256
    ranking used at every position makes the resulting JSON deterministic.
    """

    if algorithm_version != ALGORITHM_VERSION:
        raise ValueError(f"unsupported algorithm_version: {algorithm_version}")

    constraints = constraints or BoardConstraints()
    all_candidates = tuple(candidates)
    _ensure_unique_candidate_ids(all_candidates)
    rejected, eligible = _partition_candidates(all_candidates)

    generation_input = GenerationInput(
        season_id=season_id,
        player_id=player_id,
        seed=seed,
        algorithm_version=algorithm_version,
        catalog_version=catalog_version,
        candidate_ids=tuple(sorted(candidate.candidate_id for candidate in all_candidates)),
        candidate_fingerprint=candidate_fingerprint(all_candidates),
        constraints=constraints,
    )
    preflight_errors = _preflight_errors(eligible, constraints)
    if preflight_errors:
        raise BoardGenerationError(
            BoardDiagnostics(
                eligible_candidate_count=len(eligible),
                rejected_candidates=rejected,
                unsatisfied=tuple(preflight_errors),
            )
        )

    rank_salt = f"{algorithm_version}|{catalog_version}|{season_id}|{player_id}|{seed}".encode("utf-8")
    ordered_by_position = tuple(
        tuple(
            sorted(
                eligible,
                key=lambda candidate, position=position: (
                    _rank(rank_salt, position, candidate.candidate_id),
                    candidate.candidate_id,
                ),
            )
        )
        for position in range(constraints.cell_count)
    )

    stats = _SearchStats()
    selected: list[InstantiatedCandidate] = []
    solved = False
    for difficulty_layout in _difficulty_layouts(constraints, rank_salt):
        selected.clear()
        if _search(
            position=0,
            selected=selected,
            ordered_by_position=ordered_by_position,
            difficulty_layout=difficulty_layout,
            constraints=constraints,
            stats=stats,
        ):
            solved = True
            break
    if not solved:
        raise BoardGenerationError(
            BoardDiagnostics(
                eligible_candidate_count=len(eligible),
                rejected_candidates=rejected,
                attempted_assignments=stats.attempted_assignments,
                backtracks=stats.backtracks,
                unsatisfied=("eligible candidates conflict under row/board constraints",),
            )
        )

    cells = tuple(
        BoardCell(
            index=index,
            row=index // constraints.columns,
            column=index % constraints.columns,
            candidate=candidate,
        )
        for index, candidate in enumerate(selected)
    )
    diagnostics = _build_diagnostics(
        selected,
        rejected=rejected,
        eligible_count=len(eligible),
        constraints=constraints,
        stats=stats,
    )
    return BoardDraft(input=generation_input, cells=cells, diagnostics=diagnostics)


def _ensure_unique_candidate_ids(candidates: tuple[InstantiatedCandidate, ...]) -> None:
    ids = [candidate.candidate_id for candidate in candidates]
    duplicates = sorted(candidate_id for candidate_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate candidate_id: {', '.join(duplicates)}")


def _partition_candidates(
    candidates: tuple[InstantiatedCandidate, ...],
) -> tuple[tuple[RejectedCandidate, ...], tuple[InstantiatedCandidate, ...]]:
    rejected: list[RejectedCandidate] = []
    eligible: list[InstantiatedCandidate] = []
    preview_statuses = {ManifestStatus.READY_FOR_PREVIEW, ManifestStatus.READY_FOR_SEASON}
    for candidate in sorted(candidates, key=lambda item: item.candidate_id):
        if candidate.status not in preview_statuses:
            rejected.append(
                RejectedCandidate(
                    candidate_id=candidate.candidate_id,
                    manifest_code=candidate.manifest_code,
                    reason_code="manifest_not_ready",
                    detail=f"status={candidate.status.value}",
                    fallback_codes=candidate.fallback_codes,
                )
            )
        elif not candidate.eligibility.eligible:
            rejected.append(
                RejectedCandidate(
                    candidate_id=candidate.candidate_id,
                    manifest_code=candidate.manifest_code,
                    reason_code=candidate.eligibility.reason_code or "not_eligible",
                    detail=candidate.eligibility.detail,
                    fallback_codes=candidate.fallback_codes,
                )
            )
        else:
            eligible.append(candidate)
    return tuple(rejected), tuple(eligible)


def _preflight_errors(candidates: tuple[InstantiatedCandidate, ...], constraints: BoardConstraints) -> list[str]:
    errors: list[str] = []
    if len(candidates) < constraints.cell_count:
        errors.append(f"need {constraints.cell_count} eligible candidates, got {len(candidates)}")
    counts = Counter(candidate.difficulty for candidate in candidates)
    for difficulty, required in constraints.difficulty_quotas.items():
        if counts[difficulty] < required:
            errors.append(f"need {required} {difficulty.value} candidates, got {counts[difficulty]}")
    categories = {candidate.category for candidate in candidates}
    if len(categories) < constraints.min_distinct_categories:
        errors.append(f"need {constraints.min_distinct_categories} distinct categories, got {len(categories)}")
    accessible = sum(not candidate.requires_high_winrate for candidate in candidates)
    if accessible < constraints.min_accessible_per_row * constraints.rows:
        errors.append("not enough candidates accessible without a high baseline winrate")
    return errors


def _rank(salt: bytes, position: int, candidate_id: str) -> bytes:
    return sha256(salt + b"|" + str(position).encode("ascii") + b"|" + candidate_id.encode("utf-8")).digest()


def _difficulty_layouts(
    constraints: BoardConstraints, salt: bytes, *, limit: int = 256
) -> Iterator[tuple[Difficulty, ...]]:
    """Enumerate bounded valid quota layouts before assigning concrete candidates."""

    current: list[Difficulty] = []
    counts: Counter[Difficulty] = Counter()
    emitted = 0

    def walk(position: int) -> Iterator[tuple[Difficulty, ...]]:
        nonlocal emitted
        if emitted >= limit:
            return
        if position == constraints.cell_count:
            emitted += 1
            yield tuple(current)
            return

        row_start = position - (position % constraints.columns)
        difficulties = sorted(
            Difficulty,
            key=lambda difficulty: (_rank(salt, position, f"difficulty:{difficulty.value}"), difficulty.value),
        )
        for difficulty in difficulties:
            if counts[difficulty] >= constraints.difficulty_quotas[difficulty]:
                continue
            row = [*current[row_start:], difficulty]
            if row.count(Difficulty.RARE) > constraints.max_rare_per_row:
                continue
            remaining_in_row = constraints.columns - len(row)
            if row.count(Difficulty.EASY) + remaining_in_row < constraints.min_easy_per_row:
                continue

            current.append(difficulty)
            counts[difficulty] += 1
            if _difficulty_prefix_is_feasible(current, counts, constraints):
                yield from walk(position + 1)
            counts[difficulty] -= 1
            current.pop()

    yield from walk(0)


def _difficulty_prefix_is_feasible(
    current: list[Difficulty], counts: Counter[Difficulty], constraints: BoardConstraints
) -> bool:
    completed_rows, cells_in_current_row = divmod(len(current), constraints.columns)
    future_full_rows = constraints.rows - completed_rows - (1 if cells_in_current_row else 0)

    current_row = current[-cells_in_current_row:] if cells_in_current_row else []
    easy_required = future_full_rows * constraints.min_easy_per_row
    if cells_in_current_row:
        easy_required += max(0, constraints.min_easy_per_row - current_row.count(Difficulty.EASY))
    easy_remaining = constraints.difficulty_quotas[Difficulty.EASY] - counts[Difficulty.EASY]
    if easy_remaining < easy_required:
        return False

    rare_capacity = future_full_rows * constraints.max_rare_per_row
    if cells_in_current_row:
        rare_capacity += max(0, constraints.max_rare_per_row - current_row.count(Difficulty.RARE))
    rare_remaining = constraints.difficulty_quotas[Difficulty.RARE] - counts[Difficulty.RARE]
    return rare_remaining <= rare_capacity


def _search(
    *,
    position: int,
    selected: list[InstantiatedCandidate],
    ordered_by_position: tuple[tuple[InstantiatedCandidate, ...], ...],
    difficulty_layout: tuple[Difficulty, ...],
    constraints: BoardConstraints,
    stats: _SearchStats,
) -> bool:
    if position == constraints.cell_count:
        return _board_is_valid(selected, constraints)

    for candidate in ordered_by_position[position]:
        if candidate.difficulty != difficulty_layout[position]:
            continue
        stats.attempted_assignments += 1
        if not _can_place(candidate, position, selected, constraints):
            continue
        selected.append(candidate)
        if _can_still_finish(selected, constraints) and _search(
            position=position + 1,
            selected=selected,
            ordered_by_position=ordered_by_position,
            difficulty_layout=difficulty_layout,
            constraints=constraints,
            stats=stats,
        ):
            return True
        selected.pop()
        stats.backtracks += 1
    return False


def _can_place(
    candidate: InstantiatedCandidate,
    position: int,
    selected: list[InstantiatedCandidate],
    constraints: BoardConstraints,
) -> bool:
    if any(item.candidate_id == candidate.candidate_id for item in selected):
        return False
    if any(item.mechanic_key == candidate.mechanic_key for item in selected):
        return False
    if sum(item.manifest_code == candidate.manifest_code for item in selected) >= candidate.max_per_board:
        return False
    if any(
        candidate.manifest_code in item.incompatibilities or item.manifest_code in candidate.incompatibilities
        for item in selected
    ):
        return False
    if sum(item.category == candidate.category for item in selected) >= constraints.max_per_category:
        return False
    if (
        sum(item.difficulty == candidate.difficulty for item in selected)
        >= constraints.difficulty_quotas[candidate.difficulty]
    ):
        return False

    if candidate.target_opponent_id is not None:
        opponent_count = sum(item.target_opponent_id == candidate.target_opponent_id for item in selected)
        if opponent_count >= constraints.max_cells_per_opponent:
            return False

    is_peer = candidate.data_source == DataSource.PEER_CONFIRMATION
    if (
        is_peer
        and sum(item.data_source == DataSource.PEER_CONFIRMATION for item in selected)
        >= constraints.max_peer_confirmed_per_board
    ):
        return False

    row_start = position - (position % constraints.columns)
    row = [*selected[row_start:], candidate]
    if sum(item.difficulty == Difficulty.RARE for item in row) > constraints.max_rare_per_row:
        return False
    if sum(item.data_source == DataSource.PEER_CONFIRMATION for item in row) > constraints.max_peer_confirmed_per_row:
        return False

    remaining_in_row = constraints.columns - len(row)
    if sum(item.difficulty == Difficulty.EASY for item in row) + remaining_in_row < constraints.min_easy_per_row:
        return False
    accessible_count = sum(not item.requires_high_winrate for item in row)
    if accessible_count + remaining_in_row < constraints.min_accessible_per_row:
        return False
    return True


def _can_still_finish(selected: list[InstantiatedCandidate], constraints: BoardConstraints) -> bool:
    remaining_slots = constraints.cell_count - len(selected)
    difficulty_counts = Counter(candidate.difficulty for candidate in selected)
    remaining_needed = sum(
        constraints.difficulty_quotas[difficulty] - difficulty_counts[difficulty] for difficulty in Difficulty
    )
    if remaining_needed != remaining_slots:
        return False

    distinct_categories = {candidate.category for candidate in selected}
    if len(distinct_categories) + remaining_slots < constraints.min_distinct_categories:
        return False
    return True


def _board_is_valid(selected: list[InstantiatedCandidate], constraints: BoardConstraints) -> bool:
    if Counter(candidate.difficulty for candidate in selected) != Counter(constraints.difficulty_quotas):
        return False
    if len({candidate.category for candidate in selected}) < constraints.min_distinct_categories:
        return False
    return all(row.valid for row in _row_diagnostics(selected, constraints))


def _row_diagnostics(selected: list[InstantiatedCandidate], constraints: BoardConstraints) -> tuple[RowDiagnostic, ...]:
    result: list[RowDiagnostic] = []
    for row_index in range(constraints.rows):
        row = selected[row_index * constraints.columns : (row_index + 1) * constraints.columns]
        easy_count = sum(candidate.difficulty == Difficulty.EASY for candidate in row)
        rare_count = sum(candidate.difficulty == Difficulty.RARE for candidate in row)
        accessible_count = sum(not candidate.requires_high_winrate for candidate in row)
        peer_count = sum(candidate.data_source == DataSource.PEER_CONFIRMATION for candidate in row)
        result.append(
            RowDiagnostic(
                row=row_index,
                easy_count=easy_count,
                rare_count=rare_count,
                accessible_count=accessible_count,
                peer_confirmed_count=peer_count,
                categories=tuple(sorted({candidate.category for candidate in row}, key=lambda item: item.value)),
                valid=(
                    len(row) == constraints.columns
                    and easy_count >= constraints.min_easy_per_row
                    and rare_count <= constraints.max_rare_per_row
                    and accessible_count >= constraints.min_accessible_per_row
                    and peer_count <= constraints.max_peer_confirmed_per_row
                ),
            )
        )
    return tuple(result)


def _build_diagnostics(
    selected: list[InstantiatedCandidate],
    *,
    rejected: tuple[RejectedCandidate, ...],
    eligible_count: int,
    constraints: BoardConstraints,
    stats: _SearchStats,
) -> BoardDiagnostics:
    difficulty_counts = Counter(candidate.difficulty for candidate in selected)
    category_counts = Counter(candidate.category for candidate in selected)
    return BoardDiagnostics(
        eligible_candidate_count=eligible_count,
        rejected_candidates=rejected,
        attempted_assignments=stats.attempted_assignments,
        backtracks=stats.backtracks,
        difficulty_counts={difficulty: difficulty_counts[difficulty] for difficulty in Difficulty},
        category_counts={category: category_counts[category] for category in Category if category_counts[category]},
        rows=_row_diagnostics(selected, constraints),
    )
