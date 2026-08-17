"""Pure parameterizers and evaluators for production-shaped bingo candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256

from pydantic import JsonValue

from services.achievements.bingo.models import (
    AchievementTypeManifest,
    DataSource,
    EligibilityResult,
    InstantiatedCandidate,
)

PLAY_DECK_CODE = "play_deck"
_DECK_GENERAL_NAME_PARAM = "deckGeneralName"


@dataclass(frozen=True)
class FrozenDeckTarget:
    """One manually titled deck frozen from a season stats snapshot."""

    general_name: str
    title: str
    rank: int
    participations: int
    players: int

    def __post_init__(self) -> None:
        if not self.general_name.strip():
            raise ValueError("general_name must not be empty")
        if not self.title.strip():
            raise ValueError("title must not be empty")
        if self.rank < 1:
            raise ValueError("rank must be positive")
        if self.participations < 1:
            raise ValueError("participations must be positive")
        if self.players < 1:
            raise ValueError("players must be positive")


def instantiate_play_deck_candidates(
    manifest: AchievementTypeManifest,
    targets: Sequence[FrozenDeckTarget],
    *,
    stats_snapshot_id: str,
    frozen_context: Mapping[str, JsonValue] | None = None,
    attainability: float = 0.9,
) -> tuple[InstantiatedCandidate, ...]:
    """Create one concrete candidate per frozen ``general_name``.

    Several candidates deliberately share one ``mechanic_key``. The board solver can
    therefore choose any target deck, but never put two variants of the same mechanic
    on one board.
    """

    if manifest.code != PLAY_DECK_CODE:
        raise ValueError(f"expected {PLAY_DECK_CODE} manifest, got {manifest.code}")
    if manifest.data_source != DataSource.STATS_SNAPSHOT:
        raise ValueError("play_deck manifest must use stats_snapshot")
    if not stats_snapshot_id.strip():
        raise ValueError("stats_snapshot_id must not be empty")

    ordered = sorted(targets, key=lambda item: (item.rank, _normalize_general_name(item.general_name)))
    normalized_names = [_normalize_general_name(target.general_name) for target in ordered]
    if len(normalized_names) != len(set(normalized_names)):
        raise ValueError("deck targets must have unique general_name values")

    common_params = dict(frozen_context or {})
    if not ordered:
        identity = sha256(stats_snapshot_id.encode("utf-8")).hexdigest()[:16]
        return (
            InstantiatedCandidate.from_manifest(
                manifest,
                candidate_id=f"{PLAY_DECK_CODE}:unavailable:{identity}:v{manifest.version}",
                title="Колода X недоступна",
                hint="В frozen snapshot нет подходящих колод",
                eligibility=EligibilityResult(
                    eligible=False,
                    reason_code="no_frozen_deck_targets",
                    detail="stats snapshot не содержит утверждённых целей для play_deck",
                    baseline_sample=0,
                ),
                frozen_params={
                    **common_params,
                    "statsSnapshotId": stats_snapshot_id,
                },
                attainability=0.0,
            ),
        )

    candidates: list[InstantiatedCandidate] = []
    for target in ordered:
        general_name = target.general_name.strip()
        identity = sha256(f"{stats_snapshot_id}\0{_normalize_general_name(general_name)}".encode("utf-8")).hexdigest()[
            :16
        ]
        candidates.append(
            InstantiatedCandidate.from_manifest(
                manifest,
                candidate_id=f"{PLAY_DECK_CODE}:{identity}:v{manifest.version}",
                title=target.title.strip(),
                hint=f"Сыграй турнир на колоде {general_name}",
                eligibility=EligibilityResult(
                    eligible=True,
                    baseline_sample=target.participations,
                ),
                frozen_params={
                    **common_params,
                    "statsSnapshotId": stats_snapshot_id,
                    _DECK_GENERAL_NAME_PARAM: general_name,
                    "deckRank": target.rank,
                    "deckParticipations": target.participations,
                    "deckPlayers": target.players,
                },
                attainability=attainability,
            )
        )
    return tuple(candidates)


def play_deck_completed(candidate: InstantiatedCandidate, actual_general_name: str | None) -> bool:
    """Evaluate a concrete deck-X candidate against a canonical deck name."""

    if candidate.manifest_code != PLAY_DECK_CODE:
        raise ValueError(f"expected {PLAY_DECK_CODE} candidate, got {candidate.manifest_code}")
    expected = candidate.frozen_params.get(_DECK_GENERAL_NAME_PARAM)
    if not isinstance(expected, str) or not expected.strip():
        raise ValueError("play_deck candidate has no frozen deckGeneralName")
    if actual_general_name is None:
        return False
    return _normalize_general_name(actual_general_name) == _normalize_general_name(expected)


def _normalize_general_name(value: str) -> str:
    return " ".join(value.split()).casefold()
