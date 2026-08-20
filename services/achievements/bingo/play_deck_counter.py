"""Versioned three-tournament counter contract for seasonal ``play_deck`` cells."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

from pydantic import Field, JsonValue, model_validator

from services.achievements.bingo.models import (
    AchievementTypeManifest,
    DataSource,
    FrozenModel,
    InstantiatedCandidate,
    Requirement,
)
from services.achievements.bingo.parameterizers import (
    PLAY_DECK_CODE,
    FrozenDeckTarget,
    instantiate_play_deck_candidates,
)

PLAY_DECK_COUNTER_MANIFEST_VERSION = 2
PLAY_DECK_TARGET_TOURNAMENTS = 3
PLAY_DECK_TARGET_PARAM = "targetTournaments"
PLAY_DECK_COUNTER_PARAMETERIZER_KEY = "play_deck_from_frozen_catalog_v2"
PLAY_DECK_COUNTER_PROGRESS_KEY = "play_deck_tournament_counter_progress_v2"
PLAY_DECK_COUNTER_COMPLETION_KEY = "play_deck_tournament_counter_completed_v2"

_DECK_GENERAL_NAME_PARAM = "deckGeneralName"
_REQUIRED_GATES = frozenset(
    {
        Requirement.SELF_REGISTERED,
        Requirement.ACTUALLY_PLAYED,
        Requirement.TOURNAMENT_CLOSED,
        Requirement.RESULT_COMPLETE,
        Requirement.PLAYER_DECK_KNOWN,
    }
)
_COUNTER_EVIDENCE_FIELDS = (
    "stats_snapshot_id",
    "tournament_id",
    "played_at",
    "deck_general_name",
    "self_registered",
    "actually_played",
    "tournament_closed",
    "result_complete",
)


class PlayDeckTournamentEvidence(FrozenModel):
    """One tournament fact considered by the counter's pure replay."""

    tournament_id: int = Field(gt=0)
    played_at: datetime
    deck_general_name: str | None = None
    self_registered: bool
    actually_played: bool
    tournament_closed: bool
    result_complete: bool


class PlayDeckCounterProgress(FrozenModel):
    """Stable progress snapshot rebuilt from primary tournament evidence."""

    current: int = Field(ge=0)
    target: int = Field(gt=0)
    completed: bool
    counted_tournament_ids: tuple[int, ...] = ()
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_snapshot(self) -> "PlayDeckCounterProgress":
        if self.current > self.target:
            raise ValueError("current progress cannot exceed target")
        if self.current != len(self.counted_tournament_ids):
            raise ValueError("current progress must equal counted tournament count")
        if len(set(self.counted_tournament_ids)) != len(self.counted_tournament_ids):
            raise ValueError("counted tournament ids must be unique")
        if self.completed != (self.current == self.target):
            raise ValueError("completed must match current progress")
        if self.completed != (self.completed_at is not None):
            raise ValueError("completed_at must be set exactly for completed progress")
        return self


def build_play_deck_counter_manifest(base: AchievementTypeManifest) -> AchievementTypeManifest:
    """Upgrade the frozen binary v1 manifest to the explicit counter-v2 contract."""

    if base.code != PLAY_DECK_CODE:
        raise ValueError(f"expected {PLAY_DECK_CODE} manifest, got {base.code}")
    if base.version != 1:
        raise ValueError(f"counter upgrade expects manifest version 1, got {base.version}")
    if base.data_source != DataSource.STATS_SNAPSHOT:
        raise ValueError("play_deck manifest must use stats_snapshot")
    missing_gates = _REQUIRED_GATES.difference(base.requirements)
    if missing_gates:
        missing = ", ".join(sorted(gate.value for gate in missing_gates))
        raise ValueError(f"play_deck counter manifest is missing gates: {missing}")

    payload = base.model_dump(mode="python")
    payload.update(
        {
            "version": PLAY_DECK_COUNTER_MANIFEST_VERSION,
            "hint_template": "Сыграй 3 турнира на колоде {deck_general_name}",
            "parameterizer_key": PLAY_DECK_COUNTER_PARAMETERIZER_KEY,
            "progress_evaluator_key": PLAY_DECK_COUNTER_PROGRESS_KEY,
            "completion_evaluator_key": PLAY_DECK_COUNTER_COMPLETION_KEY,
            "evidence_fields": _COUNTER_EVIDENCE_FIELDS,
        }
    )
    return AchievementTypeManifest.model_validate(payload)


def instantiate_play_deck_counter_candidates(
    manifest: AchievementTypeManifest,
    targets: Sequence[FrozenDeckTarget],
    *,
    stats_snapshot_id: str,
    attainability: float,
    frozen_context: Mapping[str, JsonValue] | None = None,
) -> tuple[InstantiatedCandidate, ...]:
    """Create counter-v2 candidates with a target frozen into every snapshot."""

    _validate_counter_manifest(manifest)
    candidates = instantiate_play_deck_candidates(
        manifest,
        targets,
        stats_snapshot_id=stats_snapshot_id,
        frozen_context=frozen_context,
        attainability=attainability,
    )

    result: list[InstantiatedCandidate] = []
    for candidate in candidates:
        frozen_params = {
            **candidate.frozen_params,
            PLAY_DECK_TARGET_PARAM: PLAY_DECK_TARGET_TOURNAMENTS,
        }
        update: dict[str, object] = {"frozen_params": frozen_params}
        general_name = frozen_params.get(_DECK_GENERAL_NAME_PARAM)
        if candidate.eligibility.eligible and isinstance(general_name, str):
            update["hint"] = f"Сыграй {PLAY_DECK_TARGET_TOURNAMENTS} турнира на колоде {general_name}"
        result.append(candidate.model_copy(update=update))
    return tuple(result)


def evaluate_play_deck_counter(
    candidate: InstantiatedCandidate,
    evidence: Sequence[PlayDeckTournamentEvidence],
    *,
    activated_at: datetime,
) -> PlayDeckCounterProgress:
    """Replay eligible tournament facts and cap stable progress at the frozen target.

    Naive datetimes follow the project's database convention and are interpreted as
    UTC. Aware datetimes are converted to UTC before comparison and serialization.
    """

    expected_name, target = _validate_counter_candidate(candidate)
    activated_at_utc = _as_utc_naive(activated_at)

    unique: dict[int, tuple[datetime, str | None, bool, bool, bool, bool]] = {}
    for item in evidence:
        canonical = (
            _as_utc_naive(item.played_at),
            _normalize_general_name(item.deck_general_name),
            item.self_registered,
            item.actually_played,
            item.tournament_closed,
            item.result_complete,
        )
        previous = unique.get(item.tournament_id)
        if previous is not None and previous != canonical:
            raise ValueError(f"conflicting evidence for tournament {item.tournament_id}")
        unique[item.tournament_id] = canonical

    eligible: list[tuple[datetime, int]] = []
    for tournament_id, item in unique.items():
        played_at, deck_name, self_registered, actually_played, tournament_closed, result_complete = item
        if played_at < activated_at_utc:
            continue
        if deck_name != expected_name:
            continue
        if not (self_registered and actually_played and tournament_closed and result_complete):
            continue
        eligible.append((played_at, tournament_id))

    counted = sorted(eligible)[:target]
    return PlayDeckCounterProgress(
        current=len(counted),
        target=target,
        completed=len(counted) == target,
        counted_tournament_ids=tuple(tournament_id for _, tournament_id in counted),
        completed_at=counted[-1][0] if len(counted) == target else None,
    )


def _validate_counter_manifest(manifest: AchievementTypeManifest) -> None:
    if manifest.code != PLAY_DECK_CODE:
        raise ValueError(f"expected {PLAY_DECK_CODE} manifest, got {manifest.code}")
    expected = (
        manifest.version == PLAY_DECK_COUNTER_MANIFEST_VERSION
        and manifest.parameterizer_key == PLAY_DECK_COUNTER_PARAMETERIZER_KEY
        and manifest.progress_evaluator_key == PLAY_DECK_COUNTER_PROGRESS_KEY
        and manifest.completion_evaluator_key == PLAY_DECK_COUNTER_COMPLETION_KEY
    )
    if not expected:
        raise ValueError("play_deck manifest does not implement the counter-v2 contract")


def _validate_counter_candidate(candidate: InstantiatedCandidate) -> tuple[str, int]:
    if candidate.manifest_code != PLAY_DECK_CODE:
        raise ValueError(f"expected {PLAY_DECK_CODE} candidate, got {candidate.manifest_code}")
    if not candidate.eligibility.eligible:
        raise ValueError("cannot evaluate an ineligible play_deck candidate")
    if (
        candidate.manifest_version != PLAY_DECK_COUNTER_MANIFEST_VERSION
        or candidate.progress_evaluator_key != PLAY_DECK_COUNTER_PROGRESS_KEY
        or candidate.completion_evaluator_key != PLAY_DECK_COUNTER_COMPLETION_KEY
    ):
        raise ValueError("play_deck candidate does not implement the counter-v2 contract")

    expected_name = candidate.frozen_params.get(_DECK_GENERAL_NAME_PARAM)
    if not isinstance(expected_name, str) or not expected_name.strip():
        raise ValueError("play_deck candidate has no frozen deckGeneralName")
    target = candidate.frozen_params.get(PLAY_DECK_TARGET_PARAM)
    if isinstance(target, bool) or target != PLAY_DECK_TARGET_TOURNAMENTS:
        raise ValueError(f"play_deck candidate must freeze targetTournaments={PLAY_DECK_TARGET_TOURNAMENTS}")
    normalized_name = _normalize_general_name(expected_name)
    if normalized_name is None:  # guarded above; keeps the frozen contract explicit
        raise ValueError("play_deck candidate has no frozen deckGeneralName")
    return normalized_name, target


def _normalize_general_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split()).casefold()
    return normalized or None


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
