"""Ranked paragraph for opponent notifications, gated until public launch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from core import models
from services.ranked import (
    MOSCOW_RANKED_CLUBS,
    PRESEASON_START,
    Glicko2Rating,
    RankedEntry,
    RankedPreseasonService,
    public_ranked_score,
    update_glicko2,
)
from services.ranked_activation import RankedPublicStateService, activation_tournament_ids

RANKED_PUBLIC_START = PRESEASON_START


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
        season_start: datetime = RANKED_PUBLIC_START,
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
        own_matches = self._matches(recipient_user_id)
        own_score = public_ranked_score(
            own_rating,
            matches=own_matches,
            penalty=own_state.penalty,
        )
        opponent_state = self._states.get(opponent_user_id) if opponent_user_id is not None else None
        if opponent_state is None or not opponent_state.active:
            return RankedRoundInfo(
                own_score=own_score,
                opponent_score=None,
                opponent_hidden=True,
            )

        opponent_rating = self._rating(opponent_user_id)
        opponent_score = public_ranked_score(
            opponent_rating,
            matches=self._matches(opponent_user_id),
            penalty=opponent_state.penalty,
        )
        return RankedRoundInfo(
            own_score=own_score,
            opponent_score=opponent_score,
            opponent_hidden=False,
            win_delta=self._forecast_delta(own_rating, opponent_rating, own_matches, own_state.penalty, 1.0),
            draw_delta=self._forecast_delta(own_rating, opponent_rating, own_matches, own_state.penalty, 0.5),
            loss_delta=self._forecast_delta(own_rating, opponent_rating, own_matches, own_state.penalty, 0.0),
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
        activation_ids = activation_tournament_ids(
            self.db,
            start=self.season_start,
            end=self.now + timedelta(microseconds=1),
            clubs=MOSCOW_RANKED_CLUBS,
        )
        self._states = RankedPublicStateService(self.db).calculate(
            snapshot.included_tournament_ids,
            activation_tournament_ids=activation_ids,
        )
        self._prepared_tournament_id = tournament_id
        return True

    def _rating(self, user_id: int) -> Glicko2Rating:
        entry = self._entries.get(user_id)
        if entry is None:
            return Glicko2Rating()
        return Glicko2Rating(entry.rating, entry.deviation, entry.volatility)

    def _matches(self, user_id: int) -> int:
        entry = self._entries.get(user_id)
        return entry.matches if entry is not None else 0

    @staticmethod
    def _forecast_delta(
        own: Glicko2Rating,
        opponent: Glicko2Rating,
        matches: int,
        penalty: int,
        result: float,
    ) -> int:
        updated = update_glicko2(own, [(opponent, result)])
        return public_ranked_score(
            updated,
            matches=matches + 1,
            penalty=penalty,
        ) - public_ranked_score(own, matches=matches, penalty=penalty)
