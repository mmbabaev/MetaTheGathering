"""Read-only Moscow Pauper preseason rating calculated from bot-owned match data.

The service intentionally derives a snapshot from ``Tournament``/``RoundPairing``
instead of persisting rating points.  This keeps the first admin-only iteration safe:
the same source rows and algorithm version always produce the same leaderboard.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from services.aetherhub_links import aetherhub_tournament_key
from services.names import format_participant_name, is_single_word_name_typo, looks_like_family_name

PRESEASON_START = datetime(2026, 6, 20)
PRESEASON_END = datetime(2026, 9, 20)
RANKED_ALGORITHM_VERSION = "glicko2-v1"
MOSCOW_RANKED_CLUBS = frozenset({"edinorog", "goldfish"})

INITIAL_RATING = 1500.0
INITIAL_DEVIATION = 350.0
INITIAL_VOLATILITY = 0.06
GLICKO_SCALE = 173.7178
DEFAULT_TAU = 0.5
DEFAULT_PERIOD_DAYS = 7
DEFAULT_MIN_MATCHES = 10
DEFAULT_MIN_TOURNAMENTS = 3


@dataclass(frozen=True)
class Glicko2Rating:
    rating: float = INITIAL_RATING
    deviation: float = INITIAL_DEVIATION
    volatility: float = INITIAL_VOLATILITY

    @property
    def ranked_score(self) -> int:
        """Conservative public score: lower bound of the approximate 95% interval."""
        return round(self.rating - 2 * self.deviation)


@dataclass(frozen=True)
class RankedMatch:
    tournament_id: int
    played_at: datetime
    round_number: int
    player1_user_id: int
    player2_user_id: int
    player1_score: float


@dataclass
class RankedDataQuality:
    tournaments_scanned: int = 0
    tournaments_included: int = 0
    excluded_not_closed: int = 0
    excluded_no_pairings: int = 0
    excluded_incomplete: int = 0
    excluded_duplicate_source: int = 0
    matches_included: int = 0
    byes_excluded: int = 0
    unresolved_matches: int = 0
    inconsistent_matches: int = 0


@dataclass
class _PlayerRecord:
    tournaments: set[int] = field(default_factory=set)
    wins: int = 0
    draws: int = 0
    losses: int = 0

    @property
    def matches(self) -> int:
        return self.wins + self.draws + self.losses


@dataclass(frozen=True)
class RankedEntry:
    user_id: int
    name: str
    telegram_linked: bool
    rating: float
    deviation: float
    volatility: float
    ranked_score: int
    tournaments: int
    matches: int
    wins: int
    draws: int
    losses: int
    calibrated: bool


@dataclass(frozen=True)
class RankedSnapshot:
    start: datetime
    end: datetime
    algorithm_version: str
    entries: tuple[RankedEntry, ...]
    quality: RankedDataQuality
    included_tournament_ids: tuple[int, ...]

    def top(self, limit: int = 10, *, calibrated_only: bool = True) -> list[RankedEntry]:
        rows = (entry for entry in self.entries if entry.calibrated or not calibrated_only)
        return list(rows)[:limit]


def update_glicko2(
    current: Glicko2Rating,
    results: list[tuple[Glicko2Rating, float]],
    *,
    tau: float = DEFAULT_TAU,
    epsilon: float = 0.000001,
) -> Glicko2Rating:
    """Apply one Glicko-2 rating period.

    ``score`` is 1 for a win, 0.5 for a draw and 0 for a loss.  The implementation
    follows Mark Glickman's published worked example and also supports an empty
    period, which increases uncertainty without changing the rating.
    """

    mu = (current.rating - INITIAL_RATING) / GLICKO_SCALE
    phi = current.deviation / GLICKO_SCALE

    if not results:
        phi_star = math.sqrt(phi * phi + current.volatility * current.volatility)
        return Glicko2Rating(
            rating=current.rating,
            deviation=GLICKO_SCALE * phi_star,
            volatility=current.volatility,
        )

    converted = [
        ((opponent.rating - INITIAL_RATING) / GLICKO_SCALE, opponent.deviation / GLICKO_SCALE, score)
        for opponent, score in results
    ]

    def g(opponent_phi: float) -> float:
        return 1 / math.sqrt(1 + 3 * opponent_phi * opponent_phi / (math.pi * math.pi))

    def expected(opponent_mu: float, opponent_phi: float) -> float:
        return 1 / (1 + math.exp(-g(opponent_phi) * (mu - opponent_mu)))

    variance = 1 / sum(
        g(opponent_phi) ** 2 * expected(opponent_mu, opponent_phi) * (1 - expected(opponent_mu, opponent_phi))
        for opponent_mu, opponent_phi, _score in converted
    )
    delta = variance * sum(
        g(opponent_phi) * (score - expected(opponent_mu, opponent_phi))
        for opponent_mu, opponent_phi, score in converted
    )

    a = math.log(current.volatility * current.volatility)

    def f(x: float) -> float:
        exponent = math.exp(x)
        numerator = exponent * (delta * delta - phi * phi - variance - exponent)
        denominator = 2 * (phi * phi + variance + exponent) ** 2
        return numerator / denominator - (x - a) / (tau * tau)

    point_a = a
    if delta * delta > phi * phi + variance:
        point_b = math.log(delta * delta - phi * phi - variance)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        point_b = a - k * tau

    f_a = f(point_a)
    f_b = f(point_b)
    while abs(point_b - point_a) > epsilon:
        point_c = point_a + (point_a - point_b) * f_a / (f_b - f_a)
        f_c = f(point_c)
        if f_c * f_b <= 0:
            point_a = point_b
            f_a = f_b
        else:
            f_a /= 2
        point_b = point_c
        f_b = f_c

    volatility = math.exp(point_a / 2)
    phi_star = math.sqrt(phi * phi + volatility * volatility)
    new_phi = 1 / math.sqrt(1 / (phi_star * phi_star) + 1 / variance)
    new_mu = mu + new_phi * new_phi * sum(
        g(opponent_phi) * (score - expected(opponent_mu, opponent_phi))
        for opponent_mu, opponent_phi, score in converted
    )
    return Glicko2Rating(
        rating=GLICKO_SCALE * new_mu + INITIAL_RATING,
        deviation=GLICKO_SCALE * new_phi,
        volatility=volatility,
    )


class RankedPreseasonService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def calculate(
        self,
        *,
        start: datetime = PRESEASON_START,
        end: datetime = PRESEASON_END,
        min_matches: int = DEFAULT_MIN_MATCHES,
        min_tournaments: int = DEFAULT_MIN_TOURNAMENTS,
        period_days: int = DEFAULT_PERIOD_DAYS,
    ) -> RankedSnapshot:
        if start >= end:
            raise ValueError("rating window start must be before end")
        if min_matches <= 0 or min_tournaments <= 0 or period_days <= 0:
            raise ValueError("rating thresholds and period_days must be positive")

        matches, quality, included_tournament_ids = self._load_matches(start, end)
        states, records = self._calculate_periods(matches, start=start, period_days=period_days)
        user_ids = list(states)
        users = {
            user.id: user for user in self.db.execute(select(models.User).where(models.User.id.in_(user_ids))).scalars()
        }
        entries = []
        for user_id, state in states.items():
            user = users[user_id]
            record = records[user_id]
            name = self._display_name(user)
            entries.append(
                RankedEntry(
                    user_id=user_id,
                    name=name,
                    telegram_linked=user.tg_id > 0,
                    rating=state.rating,
                    deviation=state.deviation,
                    volatility=state.volatility,
                    ranked_score=state.ranked_score,
                    tournaments=len(record.tournaments),
                    matches=record.matches,
                    wins=record.wins,
                    draws=record.draws,
                    losses=record.losses,
                    calibrated=record.matches >= min_matches and len(record.tournaments) >= min_tournaments,
                )
            )
        entries.sort(key=lambda row: (-row.ranked_score, -row.rating, row.name.casefold(), row.user_id))
        return RankedSnapshot(
            start=start,
            end=end,
            algorithm_version=RANKED_ALGORITHM_VERSION,
            entries=tuple(entries),
            quality=quality,
            included_tournament_ids=included_tournament_ids,
        )

    def _load_matches(
        self,
        start: datetime,
        end: datetime,
    ) -> tuple[list[RankedMatch], RankedDataQuality, tuple[int, ...]]:
        quality = RankedDataQuality()
        all_users = list(self.db.execute(select(models.User)).scalars())
        identity_index: dict[tuple[str, ...], list[models.User]] = defaultdict(list)
        for user in all_users:
            key = self._name_key(" ".join(part for part in (user.first_name, user.last_name) if part))
            if key:
                identity_index[key].append(user)
        tournaments = [
            tournament
            for tournament in self.db.execute(select(models.Tournament)).scalars()
            if start <= self._played_at(tournament) < end and (tournament.club or "").casefold() in MOSCOW_RANKED_CLUBS
        ]
        tournaments.sort(key=lambda row: (self._played_at(row), row.id))
        quality.tournaments_scanned = len(tournaments)

        seen_sources: set[tuple[str, int | str]] = set()
        included_tournament_ids: list[int] = []
        result: list[RankedMatch] = []
        for tournament in tournaments:
            if tournament.status != models.TournamentStatus.CLOSED:
                quality.excluded_not_closed += 1
                continue
            pairings = list(
                self.db.execute(
                    select(models.RoundPairing)
                    .where(models.RoundPairing.tournament_id == tournament.id)
                    .order_by(
                        models.RoundPairing.round_number, models.RoundPairing.table_number, models.RoundPairing.id
                    )
                ).scalars()
            )
            if not pairings:
                quality.excluded_no_pairings += 1
                continue
            if any(
                row.opponent_name is not None and (row.player_wins is None or row.opponent_wins is None)
                for row in pairings
            ):
                quality.excluded_incomplete += 1
                continue

            source_id = aetherhub_tournament_key(tournament.aetherhub_url) if tournament.aetherhub_url else None
            source_key: tuple[str, int | str] = (
                ("aetherhub", source_id) if source_id is not None else ("tournament", tournament.id)
            )
            if source_key in seen_sources:
                quality.excluded_duplicate_source += 1
                continue
            seen_sources.add(source_key)

            quality.tournaments_included += 1
            included_tournament_ids.append(tournament.id)
            result.extend(self._canonical_matches(tournament, pairings, quality, identity_index))

        result.sort(key=lambda row: (row.played_at, row.tournament_id, row.round_number, row.player1_user_id))
        quality.matches_included = len(result)
        return result, quality, tuple(included_tournament_ids)

    def _canonical_matches(
        self,
        tournament: models.Tournament,
        pairings: list[models.RoundPairing],
        quality: RankedDataQuality,
        identity_index: dict[tuple[str, ...], list[models.User]],
    ) -> list[RankedMatch]:
        groups: dict[tuple[int, tuple[str, ...]], list[models.RoundPairing]] = defaultdict(list)
        for row in pairings:
            if row.opponent_name is None:
                quality.byes_excluded += 1
                continue
            names = tuple(sorted((self._normalized_name(row.player_name), self._normalized_name(row.opponent_name))))
            groups[row.round_number, names].append(row)

        participants = list(
            self.db.execute(
                select(models.User)
                .join(models.Participant, models.Participant.user_id == models.User.id)
                .where(models.Participant.tournament_id == tournament.id)
            ).scalars()
        )
        result: list[RankedMatch] = []
        for (round_number, _names), rows in groups.items():
            first = rows[0]
            if not self._scores_consistent(first, rows[1:]):
                quality.inconsistent_matches += 1
                continue
            player1 = self._resolve_user(first.player_name, participants, identity_index)
            player2 = self._resolve_user(first.opponent_name or "", participants, identity_index)
            if player1 is None or player2 is None or player1.id == player2.id:
                quality.unresolved_matches += 1
                continue
            player1_score = 1.0 if first.player_wins > first.opponent_wins else 0.0
            if first.player_wins == first.opponent_wins:
                player1_score = 0.5
            result.append(
                RankedMatch(
                    tournament_id=tournament.id,
                    played_at=self._played_at(tournament),
                    round_number=round_number,
                    player1_user_id=player1.id,
                    player2_user_id=player2.id,
                    player1_score=player1_score,
                )
            )
        return result

    def _resolve_user(
        self,
        name: str,
        tournament_users: list[models.User],
        identity_index: dict[tuple[str, ...], list[models.User]],
    ) -> models.User | None:
        exact = identity_index.get(self._name_key(name), [])
        if len(exact) == 1:
            return exact[0]
        real = [user for user in exact if user.tg_id > 0]
        if len(real) == 1:
            return real[0]
        candidates = [
            user
            for user in tournament_users
            if is_single_word_name_typo(
                name,
                " ".join(part for part in (user.first_name, user.last_name) if part),
            )
        ]
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _name_key(value: str) -> tuple[str, ...]:
        return tuple(
            sorted(token.rstrip(".") for token in value.casefold().replace("ё", "е").split() if token.rstrip("."))
        )

    @staticmethod
    def _scores_consistent(first: models.RoundPairing, others: list[models.RoundPairing]) -> bool:
        first_player = RankedPreseasonService._normalized_name(first.player_name)
        for row in others:
            same_direction = RankedPreseasonService._normalized_name(row.player_name) == first_player
            expected = (
                (first.player_wins, first.opponent_wins) if same_direction else (first.opponent_wins, first.player_wins)
            )
            if (row.player_wins, row.opponent_wins) != expected:
                return False
        return True

    @staticmethod
    def _played_at(tournament: models.Tournament) -> datetime:
        return tournament.started_at or tournament.created_at

    @staticmethod
    def _normalized_name(value: str) -> str:
        return " ".join(value.casefold().replace("ё", "е").split())

    @staticmethod
    def _display_name(user: models.User) -> str:
        """Return surname-first text even for legacy rows with swapped ORM fields."""
        if user.first_name and user.last_name:
            first_word = user.first_name.split()[0]
            last_word = user.last_name.split()[0]
            if looks_like_family_name(first_word) and not looks_like_family_name(last_word):
                return f"{user.first_name} {user.last_name}"
        return format_participant_name(user.first_name, user.last_name) or user.username or f"id{user.id}"

    @staticmethod
    def _calculate_periods(
        matches: list[RankedMatch],
        *,
        start: datetime,
        period_days: int,
    ) -> tuple[dict[int, Glicko2Rating], dict[int, _PlayerRecord]]:
        by_period: dict[int, list[RankedMatch]] = defaultdict(list)
        for match in matches:
            by_period[(match.played_at - start).days // period_days].append(match)

        states: dict[int, Glicko2Rating] = {}
        records: dict[int, _PlayerRecord] = defaultdict(_PlayerRecord)
        if not by_period:
            return {}, records

        for period in range(max(by_period) + 1):
            period_matches = by_period.get(period, [])
            active_ids = {
                user_id for match in period_matches for user_id in (match.player1_user_id, match.player2_user_id)
            }
            for user_id in active_ids:
                states.setdefault(user_id, Glicko2Rating())
            before = dict(states)
            results: dict[int, list[tuple[Glicko2Rating, float]]] = defaultdict(list)
            for match in period_matches:
                p1 = match.player1_user_id
                p2 = match.player2_user_id
                results[p1].append((before[p2], match.player1_score))
                results[p2].append((before[p1], 1.0 - match.player1_score))
                records[p1].tournaments.add(match.tournament_id)
                records[p2].tournaments.add(match.tournament_id)
                if match.player1_score == 1:
                    records[p1].wins += 1
                    records[p2].losses += 1
                elif match.player1_score == 0:
                    records[p1].losses += 1
                    records[p2].wins += 1
                else:
                    records[p1].draws += 1
                    records[p2].draws += 1
            states = {user_id: update_glicko2(before[user_id], results.get(user_id, [])) for user_id in before}
        return states, records
