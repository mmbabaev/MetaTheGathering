"""Versioned contracts for seasonal bingo board previews.

These models deliberately have no database or Telegram dependencies.  They describe
the frozen input and output of the pure generator used by the owner Board Lab.
"""

from __future__ import annotations

import json
from enum import Enum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

ALGORITHM_VERSION = "bingo-v1"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    RARE = "rare"


class Category(str, Enum):
    PARTICIPATION = "participation"
    PERFORMANCE = "performance"
    DECK = "deck"
    EXPLORATION = "exploration"
    SOCIAL = "social"
    H2H = "h2h"
    PEER_CONFIRMATION = "peer_confirmation"


class DataSource(str, Enum):
    DATABASE = "database"
    STATS_SNAPSHOT = "stats_snapshot"
    PEER_CONFIRMATION = "peer_confirmation"


class ManifestStatus(str, Enum):
    IDEA = "idea"
    DATA_BLOCKED = "data_blocked"
    READY_FOR_PREVIEW = "ready_for_preview"
    READY_FOR_SEASON = "ready_for_season"


class Requirement(str, Enum):
    SELF_REGISTERED = "self_registered"
    ACTUALLY_PLAYED = "actually_played"
    TOURNAMENT_CLOSED = "tournament_closed"
    RESULT_COMPLETE = "result_complete"
    OPPONENT_IDENTIFIED = "opponent_identified"
    PLAYER_DECK_KNOWN = "player_deck_known"
    OPPONENT_DECK_KNOWN = "opponent_deck_known"
    STATS_BASELINE = "stats_baseline"


class AchievementTypeManifest(FrozenModel):
    """Machine-readable template for one seasonal achievement mechanic."""

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(default=1, ge=1)
    title_template: str = Field(min_length=1)
    hint_template: str = Field(min_length=1)
    category: Category
    difficulty: Difficulty
    data_source: DataSource
    requirements: tuple[Requirement, ...]
    mechanic_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    parameterizer_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    progress_evaluator_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    completion_evaluator_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    evidence_fields: tuple[str, ...]
    incompatibilities: tuple[str, ...] = ()
    fallback_codes: tuple[str, ...] = ()
    max_per_board: int = Field(default=1, ge=1, le=16)
    status: ManifestStatus = ManifestStatus.IDEA

    @model_validator(mode="after")
    def validate_references(self) -> "AchievementTypeManifest":
        if self.code in self.incompatibilities:
            raise ValueError("manifest cannot be incompatible with itself")
        if self.code in self.fallback_codes:
            raise ValueError("manifest cannot fall back to itself")
        if len(set(self.requirements)) != len(self.requirements):
            raise ValueError("requirements must be unique")
        if not self.evidence_fields:
            raise ValueError("evidence_fields must not be empty")
        if len(set(self.evidence_fields)) != len(self.evidence_fields):
            raise ValueError("evidence_fields must be unique")
        if len(set(self.incompatibilities)) != len(self.incompatibilities):
            raise ValueError("incompatibilities must be unique")
        if len(set(self.fallback_codes)) != len(self.fallback_codes):
            raise ValueError("fallback_codes must be unique")
        return self


class EligibilityResult(FrozenModel):
    """Why a concrete candidate can or cannot enter this player's board."""

    eligible: bool
    reason_code: str | None = None
    detail: str | None = None
    baseline_sample: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_reason_for_rejection(self) -> "EligibilityResult":
        if not self.eligible and not self.reason_code:
            raise ValueError("ineligible candidate must have reason_code")
        return self


class InstantiatedCandidate(FrozenModel):
    """A manifest instantiated with frozen player/season-specific parameters."""

    candidate_id: str = Field(min_length=1)
    manifest_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    manifest_version: int = Field(ge=1)
    mechanic_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=1)
    hint: str = Field(min_length=1)
    category: Category
    difficulty: Difficulty
    data_source: DataSource
    requirements: tuple[Requirement, ...]
    parameterizer_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    progress_evaluator_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    completion_evaluator_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    evidence_fields: tuple[str, ...]
    frozen_params: dict[str, JsonValue] = Field(default_factory=dict)
    eligibility: EligibilityResult
    incompatibilities: tuple[str, ...] = ()
    fallback_codes: tuple[str, ...] = ()
    max_per_board: int = Field(default=1, ge=1, le=16)
    requires_high_winrate: bool = False
    attainability: float = Field(ge=0.0, le=1.0)
    target_opponent_id: str | None = None
    status: ManifestStatus

    @classmethod
    def from_manifest(
        cls,
        manifest: AchievementTypeManifest,
        *,
        candidate_id: str,
        title: str,
        hint: str,
        eligibility: EligibilityResult,
        frozen_params: dict[str, JsonValue] | None = None,
        attainability: float,
        requires_high_winrate: bool = False,
        target_opponent_id: str | None = None,
    ) -> "InstantiatedCandidate":
        return cls(
            candidate_id=candidate_id,
            manifest_code=manifest.code,
            manifest_version=manifest.version,
            mechanic_key=manifest.mechanic_key,
            title=title,
            hint=hint,
            category=manifest.category,
            difficulty=manifest.difficulty,
            data_source=manifest.data_source,
            requirements=manifest.requirements,
            parameterizer_key=manifest.parameterizer_key,
            progress_evaluator_key=manifest.progress_evaluator_key,
            completion_evaluator_key=manifest.completion_evaluator_key,
            evidence_fields=manifest.evidence_fields,
            frozen_params=frozen_params or {},
            eligibility=eligibility,
            incompatibilities=manifest.incompatibilities,
            fallback_codes=manifest.fallback_codes,
            max_per_board=manifest.max_per_board,
            requires_high_winrate=requires_high_winrate,
            attainability=attainability,
            target_opponent_id=target_opponent_id,
            status=manifest.status,
        )


def default_difficulty_quotas() -> dict[Difficulty, int]:
    return {
        Difficulty.EASY: 4,
        Difficulty.MEDIUM: 6,
        Difficulty.HARD: 4,
        Difficulty.RARE: 2,
    }


class BoardConstraints(FrozenModel):
    rows: int = Field(default=4, ge=1, le=8)
    columns: int = Field(default=4, ge=1, le=8)
    difficulty_quotas: dict[Difficulty, int] = Field(default_factory=default_difficulty_quotas)
    min_easy_per_row: int = Field(default=1, ge=0)
    max_rare_per_row: int = Field(default=1, ge=0)
    min_accessible_per_row: int = Field(default=1, ge=0)
    min_distinct_categories: int = Field(default=4, ge=1)
    max_per_category: int = Field(default=6, ge=1)
    max_peer_confirmed_per_board: int = Field(default=2, ge=0)
    max_peer_confirmed_per_row: int = Field(default=1, ge=0)
    max_cells_per_opponent: int = Field(default=1, ge=0)

    @property
    def cell_count(self) -> int:
        return self.rows * self.columns

    @model_validator(mode="after")
    def validate_board_shape(self) -> "BoardConstraints":
        if set(self.difficulty_quotas) != set(Difficulty):
            raise ValueError("difficulty_quotas must define every difficulty")
        if sum(self.difficulty_quotas.values()) != self.cell_count:
            raise ValueError("difficulty quotas must add up to board cell count")
        if self.min_easy_per_row * self.rows > self.difficulty_quotas[Difficulty.EASY]:
            raise ValueError("easy quota cannot satisfy every row")
        if self.max_rare_per_row * self.rows < self.difficulty_quotas[Difficulty.RARE]:
            raise ValueError("rare quota exceeds per-row capacity")
        if self.min_easy_per_row > self.columns or self.min_accessible_per_row > self.columns:
            raise ValueError("row minimum cannot exceed column count")
        if self.min_distinct_categories > len(Category):
            raise ValueError("min_distinct_categories exceeds known category count")
        return self


class RejectedCandidate(FrozenModel):
    candidate_id: str
    manifest_code: str
    reason_code: str
    detail: str | None = None
    fallback_codes: tuple[str, ...] = ()


class RowDiagnostic(FrozenModel):
    row: int
    easy_count: int
    rare_count: int
    accessible_count: int
    peer_confirmed_count: int
    categories: tuple[Category, ...]
    valid: bool


class BoardDiagnostics(FrozenModel):
    eligible_candidate_count: int
    rejected_candidates: tuple[RejectedCandidate, ...] = ()
    attempted_assignments: int = 0
    backtracks: int = 0
    difficulty_counts: dict[Difficulty, int] = Field(default_factory=dict)
    category_counts: dict[Category, int] = Field(default_factory=dict)
    rows: tuple[RowDiagnostic, ...] = ()
    unsatisfied: tuple[str, ...] = ()


class GenerationInput(FrozenModel):
    season_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    seed: int
    algorithm_version: str = Field(min_length=1)
    catalog_version: str = Field(min_length=1)
    candidate_ids: tuple[str, ...]
    candidate_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    constraints: BoardConstraints


class BoardCell(FrozenModel):
    index: int = Field(ge=0)
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    candidate: InstantiatedCandidate


class BoardDraft(FrozenModel):
    input: GenerationInput
    cells: tuple[BoardCell, ...]
    diagnostics: BoardDiagnostics

    def stable_json(self) -> str:
        """Canonical JSON used by exports and byte-for-byte determinism tests."""
        return stable_json(self.model_dump(mode="json"))


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def candidate_fingerprint(candidates: tuple[InstantiatedCandidate, ...]) -> str:
    payload = [
        candidate.model_dump(mode="json") for candidate in sorted(candidates, key=lambda item: item.candidate_id)
    ]
    return sha256(stable_json(payload).encode("utf-8")).hexdigest()
