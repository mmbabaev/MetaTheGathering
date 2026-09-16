"""Endstep Swiss table-title helpers shared by business and Telegram UI layers."""

from __future__ import annotations

from core import models

ENDSTEP_RU_CLUB = "Endstep-ru"
ENDSTEP_TABLE_TITLE_PREFIX = "MTG Pauper Endstep"
COPY_TEXT_LIMIT = 256


def is_endstep_swiss(tournament: models.Tournament) -> bool:
    return (
        tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS
        and (tournament.club or "").casefold() == ENDSTEP_RU_CLUB.casefold()
    )


def format_endstep_table_title(match: models.RoundMatch) -> str:
    """Return a Telegram-compatible copy-button value for one playable match."""
    title = f"{ENDSTEP_TABLE_TITLE_PREFIX} {match.player1_name} - {match.player2_name}"
    return title[:COPY_TEXT_LIMIT]
