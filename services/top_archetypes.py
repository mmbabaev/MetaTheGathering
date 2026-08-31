"""Weekly snapshot of the decks shown in the global archetype menu."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.orm import Session

from core import models
from services.season_stats import SeasonStatsService

logger = logging.getLogger(__name__)

TOP_ARCHETYPE_COUNT = 10
TOP_ARCHETYPE_WINDOW_DAYS = 365


@dataclass(frozen=True)
class TopArchetypeAssignment:
    rank: int
    general_name: str
    archetype_id: int
    archetype_name: str
    participations: int
    players: int


@dataclass(frozen=True)
class TopArchetypeRefreshResult:
    updated: bool
    assignments: tuple[TopArchetypeAssignment, ...]
    complete_tournaments: int


class TopArchetypeSnapshotService:
    """Calculates and persists the weekly top-deck menu snapshot.

    Popularity is calculated by :class:`SeasonStatsService`: only closed
    tournaments with complete pairings count, no-shows are excluded, and raw deck
    variants are grouped by ``general_name``.  The menu still needs a concrete
    public ``Archetype`` row, so an exact public name is preferred; otherwise the
    most-used public variant is selected.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def refresh(
        self,
        *,
        as_of: datetime,
        window_days: int = TOP_ARCHETYPE_WINDOW_DAYS,
        limit: int = TOP_ARCHETYPE_COUNT,
    ) -> TopArchetypeRefreshResult:
        snapshot = SeasonStatsService(self.db).build_snapshot(
            as_of=as_of,
            history_days=window_days,
            deck_window_days=window_days,
            top_decks=limit,
        )

        assignments: list[TopArchetypeAssignment] = []
        archetypes: list[models.Archetype] = []
        for deck in snapshot.popular_decks:
            archetype = self._representative(deck.deck)
            if archetype is None:
                logger.warning(
                    "Weekly top archetypes: no public archetype for general_name=%r (rank %s)",
                    deck.deck,
                    deck.rank,
                )
                continue
            archetypes.append(archetype)
            assignments.append(
                TopArchetypeAssignment(
                    rank=deck.rank,
                    general_name=deck.deck,
                    archetype_id=archetype.id,
                    archetype_name=archetype.name,
                    participations=deck.participations,
                    players=deck.players,
                )
            )

        # An empty source is more likely an import/data-quality problem than a real
        # empty metagame. Keep the last known good menu instead of erasing it.
        if not assignments:
            logger.warning(
                "Weekly top archetypes: snapshot is empty; keeping the previous ranks (complete tournaments=%s)",
                snapshot.quality.complete_tournaments,
            )
            return TopArchetypeRefreshResult(
                updated=False,
                assignments=(),
                complete_tournaments=snapshot.quality.complete_tournaments,
            )

        try:
            self.db.execute(update(models.Archetype).values(meta_rank=None))
            for archetype, assignment in zip(archetypes, assignments, strict=True):
                archetype.meta_rank = assignment.rank
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return TopArchetypeRefreshResult(
            updated=True,
            assignments=tuple(assignments),
            complete_tournaments=snapshot.quality.complete_tournaments,
        )

    def _representative(self, general_name: str) -> models.Archetype | None:
        usage_count = (
            select(func.count(models.Participant.id))
            .join(models.Tournament, models.Tournament.id == models.Participant.tournament_id)
            .where(
                models.Participant.archetype_id == models.Archetype.id,
                models.Tournament.status != models.TournamentStatus.REGISTRATION,
            )
            .correlate(models.Archetype)
            .scalar_subquery()
        )
        stmt = (
            select(models.Archetype)
            .where(
                models.Archetype.is_custom.is_(False),
                or_(
                    models.Archetype.name == general_name,
                    models.Archetype.general_name == general_name,
                ),
            )
            .order_by(
                case((models.Archetype.name == general_name, 0), else_=1),
                usage_count.desc(),
                models.Archetype.name.asc(),
                models.Archetype.id.asc(),
            )
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()
