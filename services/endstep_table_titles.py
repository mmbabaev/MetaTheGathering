"""Endstep Swiss table-title helpers shared by business and Telegram UI layers."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models

ENDSTEP_RU_CLUB = "Endstep-ru"
ENDSTEP_DRAFT_CLUB = "Endstep draft"
ENDSTEP_TABLE_TITLE = "MTG Pauper Endstep - table"

# Публичное имя регулярных онлайн-турниров Endstep-ru («Концеход Pauper #N»).
# Клуб в БД остаётся «Endstep-ru»: на него завязаны internal Swiss, лидерборды и импорт.
KONETSKHOD_NAME = "Концеход"


def is_endstep_swiss(tournament: models.Tournament) -> bool:
    return tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS and (
        tournament.club or ""
    ).casefold() in {ENDSTEP_RU_CLUB.casefold(), ENDSTEP_DRAFT_CLUB.casefold()}


def is_konetskhod_club(club_name: str | None) -> bool:
    """Регулярный онлайн-турнир Endstep-ru (draft — не Концеход)."""
    return (club_name or "").casefold() == ENDSTEP_RU_CLUB.casefold()


def konetskhod_tournament_count(db: Session) -> int:
    """Сколько турниров Концехода уже создано (по club или старому заголовку)."""
    return int(
        db.execute(
            select(func.count())
            .select_from(models.Tournament)
            .where((models.Tournament.club == ENDSTEP_RU_CLUB) | models.Tournament.title.ilike(f"%{ENDSTEP_RU_CLUB}%"))
        ).scalar_one()
    )


def konetskhod_title(db: Session, title_prefix: str = "") -> str:
    """Заголовок следующего турнира: «⏭️🦶 Концеход Pauper #N»."""
    number = konetskhod_tournament_count(db) + 1
    return f"{title_prefix}{KONETSKHOD_NAME} Pauper #{number}"
