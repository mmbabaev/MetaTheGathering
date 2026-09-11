"""Russian Endstep Pauper leaderboard projected from bot tournament members."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models
from services.endstep import EndstepClient, EndstepLeaderboardPlayer

ENDSTEP_RU_CLUB = "Endstep-ru"


@dataclass(frozen=True)
class EndstepRuLeaderboardRow:
    position: int
    user_id: int
    username: str
    site_rank: int | None
    rating: int
    rd: int
    wins: int
    losses: int
    draws: int
    provisional: bool


@dataclass(frozen=True)
class EndstepRuLeaderboard:
    generated_at: datetime
    candidate_count: int
    rows: tuple[EndstepRuLeaderboardRow, ...]
    missing_usernames: tuple[str, ...]
    ambiguous_usernames: tuple[str, ...] = ()


class EndstepRuLeaderboardService:
    """Match Endstep-ru tournament members to the current Endstep Pauper ladder."""

    def __init__(self, db: Session, client: EndstepClient | None = None) -> None:
        self.db = db
        self.client = client

    def _candidates(self) -> list[models.User]:
        return list(
            self.db.execute(
                select(models.User)
                .join(models.Participant, models.Participant.user_id == models.User.id)
                .join(models.Tournament, models.Tournament.id == models.Participant.tournament_id)
                .where(
                    models.User.tg_id > 0,
                    models.User.endstep_username.is_not(None),
                    func.lower(models.Tournament.club) == ENDSTEP_RU_CLUB.casefold(),
                )
                .distinct()
                .order_by(models.User.id)
            )
            .scalars()
            .all()
        )

    def calculate(self) -> EndstepRuLeaderboard:
        if self.client is None:
            raise RuntimeError("EndstepClient is required to refresh the leaderboard")
        candidates = self._candidates()
        by_username: dict[str, models.User] = {}
        for user in candidates:
            username = (user.endstep_username or "").strip()
            if username:
                by_username.setdefault(username.casefold(), user)

        usernames = [user.endstep_username.strip() for user in by_username.values()]
        if not usernames:
            return EndstepRuLeaderboard(
                generated_at=models.utc_now(),
                candidate_count=0,
                rows=(),
                missing_usernames=(),
            )

        lookups = self.client.find_players(usernames)
        matched: list[tuple[models.User, EndstepLeaderboardPlayer]] = []
        missing: list[str] = []
        ambiguous: list[str] = []
        for lookup in lookups:
            user = by_username[lookup.requested_username.casefold()]
            if len(lookup.exact_matches) > 1:
                ambiguous.append(lookup.requested_username)
            elif lookup.player is None:
                missing.append(lookup.requested_username)
            else:
                matched.append((user, lookup.player))

        matched.sort(
            key=lambda item: (
                item[1].rank is None,
                item[1].rank if item[1].rank is not None else 0,
                -item[1].rating,
                item[1].username.casefold(),
                item[0].id,
            )
        )
        rows = tuple(
            EndstepRuLeaderboardRow(
                position=position,
                user_id=user.id,
                username=player.username,
                site_rank=player.rank,
                rating=player.rating,
                rd=player.rd,
                wins=player.wins,
                losses=player.losses,
                draws=player.draws,
                provisional=player.provisional,
            )
            for position, (user, player) in enumerate(matched, start=1)
        )
        return EndstepRuLeaderboard(
            generated_at=models.utc_now(),
            candidate_count=len(by_username),
            rows=rows,
            missing_usernames=tuple(sorted(missing, key=str.casefold)),
            ambiguous_usernames=tuple(sorted(ambiguous, key=str.casefold)),
        )

    def refresh(self) -> EndstepRuLeaderboard:
        """Fetch Endstep and atomically append one immutable local snapshot."""

        snapshot = self.calculate()
        self.db.add(
            models.EndstepRuLeaderboardSnapshot(
                generated_at=snapshot.generated_at,
                candidate_count=snapshot.candidate_count,
                rows_json=json.dumps(
                    [asdict(row) for row in snapshot.rows],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                missing_usernames_json=json.dumps(
                    snapshot.missing_usernames,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                ambiguous_usernames_json=json.dumps(
                    snapshot.ambiguous_usernames,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )
        self.db.commit()
        return snapshot

    def latest(self) -> EndstepRuLeaderboard | None:
        """Read the latest successful snapshot without contacting Endstep."""

        stored = (
            self.db.execute(
                select(models.EndstepRuLeaderboardSnapshot).order_by(
                    models.EndstepRuLeaderboardSnapshot.generated_at.desc(),
                    models.EndstepRuLeaderboardSnapshot.id.desc(),
                )
            )
            .scalars()
            .first()
        )
        if stored is None:
            return None
        return EndstepRuLeaderboard(
            generated_at=stored.generated_at,
            candidate_count=stored.candidate_count,
            rows=tuple(EndstepRuLeaderboardRow(**row) for row in json.loads(stored.rows_json)),
            missing_usernames=tuple(json.loads(stored.missing_usernames_json)),
            ambiguous_usernames=tuple(json.loads(stored.ambiguous_usernames_json)),
        )
