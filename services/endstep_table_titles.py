"""Endstep Swiss table-title helpers shared by business and Telegram UI layers."""

from __future__ import annotations

from core import models

ENDSTEP_RU_CLUB = "Endstep-ru"
ENDSTEP_DRAFT_CLUB = "Endstep draft"
ENDSTEP_TABLE_TITLE = "MTG Pauper Endstep - table"


def is_endstep_swiss(tournament: models.Tournament) -> bool:
    return tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS and (
        tournament.club or ""
    ).casefold() in {ENDSTEP_RU_CLUB.casefold(), ENDSTEP_DRAFT_CLUB.casefold()}
