"""Ачивки: определения, правила, движок выдачи и отчёт.

План и обоснование решений — docs/achievements.md.
"""

from services.achievements.definitions import ACHIEVEMENTS, AchievementDef, Codes
from services.achievements.history import AchievementHistory, counts_for_achievements
from services.achievements.report import build_report
from services.achievements.service import (
    AchievementService,
    AchievementView,
    AppliedResult,
    GrantedAchievement,
    ProgressChange,
)

__all__ = [
    "ACHIEVEMENTS",
    "AchievementDef",
    "AchievementHistory",
    "AchievementService",
    "AchievementView",
    "AppliedResult",
    "Codes",
    "GrantedAchievement",
    "ProgressChange",
    "build_report",
    "counts_for_achievements",
]
