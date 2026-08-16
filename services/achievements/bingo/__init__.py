"""Pure contracts, fixtures and generator for seasonal bingo board previews."""

from services.achievements.bingo.fixtures import (
    FIXTURE_CATALOG_VERSION,
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

__all__ = [
    "ALGORITHM_VERSION",
    "FIXTURE_CATALOG_VERSION",
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
    "InstantiatedCandidate",
    "ManifestStatus",
    "Requirement",
    "fixture_candidates",
    "generate_board",
]
