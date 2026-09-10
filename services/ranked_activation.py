"""Durable self-activation evidence and public Ranked penalty cycles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models

RANKED_ACTIVATION_SELF_BOT = "self_bot"
RANKED_ACTIVATION_CELLAR = "cellar"
RANKED_ACTIVATION_SOURCES = frozenset({RANKED_ACTIVATION_SELF_BOT, RANKED_ACTIVATION_CELLAR})
RANKED_PUBLIC_PENALTY = 50
RANKED_MISS_LIMIT = 2


def activate_participant(
    participant: models.Participant,
    source: str | None,
    *,
    activated_at: datetime | None = None,
) -> None:
    """Store the first qualifying self-action; later edits cannot erase it."""
    if source is None:
        return
    if source not in RANKED_ACTIVATION_SOURCES:
        raise ValueError(f"unsupported Ranked activation source: {source}")
    if participant.ranked_activated_at is None:
        participant.ranked_activated_at = activated_at or models.utc_now()
        participant.ranked_activation_source = source
    elif participant.ranked_activation_source == RANKED_ACTIVATION_CELLAR and source == RANKED_ACTIVATION_SELF_BOT:
        # A direct bot action survives a later Cellar cancellation.
        participant.ranked_activation_source = source


def merge_participant_activation(
    participant: models.Participant,
    activated_at: datetime | None,
    source: str | None,
) -> None:
    """Merge activation evidence without losing a stronger ``self_bot`` marker."""
    if activated_at is None or source not in RANKED_ACTIVATION_SOURCES:
        return
    if participant.ranked_activated_at is None or activated_at < participant.ranked_activated_at:
        participant.ranked_activated_at = activated_at
    if participant.ranked_activation_source is None or source == RANKED_ACTIVATION_SELF_BOT:
        participant.ranked_activation_source = source


@dataclass
class RankedPublicState:
    active: bool = False
    missed_tournaments: int = 0
    penalty: int = 0
    penalty_cycles: int = 0


class RankedPublicStateService:
    """Rebuild public eligibility deterministically from tournament activations."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def calculate(
        self,
        included_tournament_ids: tuple[int, ...],
        *,
        current_tournament_id: int | None = None,
    ) -> dict[int, RankedPublicState]:
        closed_ids = set(included_tournament_ids)
        query_ids = set(closed_ids)
        if current_tournament_id is not None:
            query_ids.add(current_tournament_id)
        if not query_ids:
            return {}

        tournaments = {
            tournament.id: tournament
            for tournament in self.db.execute(
                select(models.Tournament).where(models.Tournament.id.in_(query_ids))
            ).scalars()
        }
        participants = list(
            self.db.execute(select(models.Participant).where(models.Participant.tournament_id.in_(query_ids))).scalars()
        )
        by_tournament: dict[int, list[models.Participant]] = {}
        for participant in participants:
            by_tournament.setdefault(participant.tournament_id, []).append(participant)

        states: dict[int, RankedPublicState] = {}
        ordered_closed = sorted(
            (tournaments[tournament_id] for tournament_id in closed_ids if tournament_id in tournaments),
            key=lambda tournament: (tournament.started_at or tournament.created_at, tournament.id),
        )
        for tournament in ordered_closed:
            for participant in by_tournament.get(tournament.id, []):
                state = states.setdefault(participant.user_id, RankedPublicState())
                if self._activated(participant):
                    state.active = True
                    state.missed_tournaments = 0
                elif state.active:
                    state.missed_tournaments += 1
                    if state.missed_tournaments >= RANKED_MISS_LIMIT:
                        state.active = False
                        state.missed_tournaments = 0
                        state.penalty += RANKED_PUBLIC_PENALTY
                        state.penalty_cycles += 1

        if current_tournament_id is not None and current_tournament_id not in closed_ids:
            for participant in by_tournament.get(current_tournament_id, []):
                if not self._activated(participant):
                    continue
                state = states.setdefault(participant.user_id, RankedPublicState())
                state.active = True
                state.missed_tournaments = 0
        return states

    @staticmethod
    def _activated(participant: models.Participant) -> bool:
        return (
            participant.ranked_activated_at is not None
            and participant.ranked_activation_source in RANKED_ACTIVATION_SOURCES
        )
