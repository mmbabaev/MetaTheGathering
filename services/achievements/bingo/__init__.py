"""Pure contracts, fixtures and generator for seasonal bingo board previews."""

from services.achievements.bingo.fixtures import (
    FIXTURE_CATALOG_VERSION,
    FIXTURE_DECK_STATS_SNAPSHOT_ID,
    FIXTURE_DECK_TARGETS,
    PREVIEW_MANIFESTS,
    FixturePersona,
    fixture_candidates,
)
from services.achievements.bingo.generator import BoardGenerationError, generate_board
from services.achievements.bingo.models import (
    ALGORITHM_VERSION,
    AchievementTypeManifest,
    BoardConstraints,
    BoardDraft,
    Category,
    DataSource,
    Difficulty,
    EligibilityResult,
    InstantiatedCandidate,
    ManifestStatus,
    Requirement,
)
from services.achievements.bingo.parameterizers import (
    PLAY_DECK_CODE,
    FrozenDeckTarget,
    instantiate_play_deck_candidates,
    play_deck_completed,
)

__all__ = [
    "ALGORITHM_VERSION",
    "FIXTURE_CATALOG_VERSION",
    "FIXTURE_DECK_STATS_SNAPSHOT_ID",
    "FIXTURE_DECK_TARGETS",
    "PLAY_DECK_CODE",
    "PREVIEW_MANIFESTS",
    "AchievementTypeManifest",
    "BoardConstraints",
    "BoardDraft",
    "BoardGenerationError",
    "Category",
    "DataSource",
    "Difficulty",
    "EligibilityResult",
    "FixturePersona",
    "FrozenDeckTarget",
    "InstantiatedCandidate",
    "ManifestStatus",
    "Requirement",
    "fixture_candidates",
    "generate_board",
    "instantiate_play_deck_candidates",
    "play_deck_completed",
]
