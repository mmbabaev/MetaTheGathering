"""Public Moscow Pauper Ranked leaderboard derived from bot-owned data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from services.ranked import (
    MOSCOW_RANKED_CLUBS,
    PRESEASON_START,
    Glicko2Rating,
    RankedPreseasonService,
    public_ranked_score,
)
from services.ranked_activation import RankedPublicStateService, activation_tournament_ids

RANKED_PUBLIC_START = PRESEASON_START


@dataclass(frozen=True)
class RankedLeaderboardRow:
    position: int
    user_id: int
    name: str
    score: int


@dataclass(frozen=True)
class RankedLeaderboard:
    generated_at: datetime
    rows: tuple[RankedLeaderboardRow, ...]


class RankedLeaderboardService:
    """Build the public projection without exposing inactive player ratings."""

    def __init__(
        self,
        db: Session,
        *,
        start: datetime = RANKED_PUBLIC_START,
        now: datetime | None = None,
    ) -> None:
        self.db = db
        self.start = start
        self.now = now or models.utc_now()

    def calculate(self) -> RankedLeaderboard:
        end = self.now + timedelta(microseconds=1)
        snapshot = RankedPreseasonService(self.db).calculate(start=self.start, end=end)
        activation_ids = activation_tournament_ids(
            self.db,
            start=self.start,
            end=end,
            clubs=MOSCOW_RANKED_CLUBS,
        )
        states = RankedPublicStateService(self.db).calculate(
            snapshot.included_tournament_ids,
            activation_tournament_ids=activation_ids,
        )
        active_user_ids = [user_id for user_id, state in states.items() if state.active]
        users = {
            user.id: user
            for user in self.db.execute(select(models.User).where(models.User.id.in_(active_user_ids))).scalars()
        }
        ratings = {entry.user_id: entry for entry in snapshot.entries}
        unordered: list[tuple[int, str, int]] = []
        for user_id in active_user_ids:
            user = users.get(user_id)
            if user is None:
                continue
            entry = ratings.get(user_id)
            rating = (
                Glicko2Rating(entry.rating, entry.deviation, entry.volatility) if entry is not None else Glicko2Rating()
            )
            unordered.append(
                (
                    user_id,
                    RankedPreseasonService._display_name(user),
                    public_ranked_score(
                        rating,
                        matches=entry.matches if entry is not None else 0,
                        penalty=states[user_id].penalty,
                    ),
                )
            )
        unordered.sort(key=lambda row: (-row[2], row[1].casefold(), row[0]))
        rows = tuple(
            RankedLeaderboardRow(position=index, user_id=user_id, name=name, score=score)
            for index, (user_id, name, score) in enumerate(unordered, start=1)
        )
        return RankedLeaderboard(generated_at=self.now, rows=rows)
