"""Ranked paragraph for opponent notifications, gated until public launch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from core import models
from services.ranked import (
    MOSCOW_RANKED_CLUBS,
    Glicko2Rating,
    RankedEntry,
    RankedPreseasonService,
    update_glicko2,
)
from services.ranked_activation import RankedPublicStateService

RANKED_FIRST_SEASON_START = datetime(2026, 9, 20)


@dataclass(frozen=True)
class RankedRoundInfo:
    own_score: int
    opponent_score: int | None
    opponent_hidden: bool
    win_delta: int | None = None
    draw_delta: int | None = None
    loss_delta: int | None = None


class RankedRoundInfoService:
    """Calculate one shared season snapshot and project individual pairings."""

    def __init__(
        self,
        db: Session,
        *,
        season_start: datetime = RANKED_FIRST_SEASON_START,
        now: datetime | None = None,
    ) -> None:
        self.db = db
        self.season_start = season_start
        self.now = now or models.utc_now()
        self._prepared_tournament_id: int | None = None
        self._entries: dict[int, RankedEntry] = {}
        self._states = {}

    def for_pairing(
        self,
        tournament_id: int,
        recipient_user_id: int,
        opponent_user_id: int | None,
    ) -> RankedRoundInfo | None:
        if not self._prepare(tournament_id):
            return None
        own_state = self._states.get(recipient_user_id)
        if own_state is None or not own_state.active:
            return None

        own_rating = self._rating(recipient_user_id)
        own_score = own_rating.ranked_score - own_state.penalty
        opponent_state = self._states.get(opponent_user_id) if opponent_user_id is not None else None
        if opponent_state is None or not opponent_state.active:
            return RankedRoundInfo(
                own_score=own_score,
                opponent_score=None,
                opponent_hidden=True,
            )

        opponent_rating = self._rating(opponent_user_id)
        opponent_score = opponent_rating.ranked_score - opponent_state.penalty
        return RankedRoundInfo(
            own_score=own_score,
            opponent_score=opponent_score,
            opponent_hidden=False,
            win_delta=self._forecast_delta(own_rating, opponent_rating, 1.0),
            draw_delta=self._forecast_delta(own_rating, opponent_rating, 0.5),
            loss_delta=self._forecast_delta(own_rating, opponent_rating, 0.0),
        )

    def _prepare(self, tournament_id: int) -> bool:
        if self._prepared_tournament_id == tournament_id:
            return True
        if self.now <= self.season_start:
            return False
        tournament = self.db.get(models.Tournament, tournament_id)
        if tournament is None or (tournament.club or "").casefold() not in MOSCOW_RANKED_CLUBS:
            return False

        snapshot = RankedPreseasonService(self.db).calculate(
            start=self.season_start,
            end=self.now + timedelta(microseconds=1),
        )
        self._entries = {entry.user_id: entry for entry in snapshot.entries}
        self._states = RankedPublicStateService(self.db).calculate(
            snapshot.included_tournament_ids,
            current_tournament_id=tournament_id,
        )
        self._prepared_tournament_id = tournament_id
        return True

    def _rating(self, user_id: int) -> Glicko2Rating:
        entry = self._entries.get(user_id)
        if entry is None:
            return Glicko2Rating()
        return Glicko2Rating(entry.rating, entry.deviation, entry.volatility)

    @staticmethod
    def _forecast_delta(own: Glicko2Rating, opponent: Glicko2Rating, result: float) -> int:
        return update_glicko2(own, [(opponent, result)]).ranked_score - own.ranked_score
