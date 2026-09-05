"""Opt-in internal Swiss tournament engine.

The service deliberately writes the existing ``RoundPairing`` compatibility
rows and canonical ``RoundMatch`` rows.  Result reporting, exports, tournament
status and club pairing publication therefore keep using the same data path as
an AetherHub-backed online tournament.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from core import models
from services.names import format_participant_name
from services.round_results import FINAL_STATUSES, RoundResultError, RoundResultsService
from services.user import UserService

MATCH_WIN_POINTS = 3
MATCH_DRAW_POINTS = 1
MIN_PERCENTAGE = 1 / 3


def recommended_swiss_rounds(player_count: int) -> int:
    """Recommended rounds for an individual Constructed Swiss tournament.

    The 4+ player ranges follow the individual-event minimum and Appendix E of
    the Magic Tournament Rules. Smaller ranges are useful only for debug/local
    events below the sanctioned-event minimum.
    """

    if player_count <= 1:
        return 0
    if player_count == 2:
        return 1
    if player_count == 3:
        return 2
    if player_count == 4:
        return 3
    if player_count <= 8:
        return 3
    if player_count <= 32:
        return 5
    if player_count <= 64:
        return 6
    if player_count <= 128:
        return 7
    if player_count <= 226:
        return 8
    if player_count <= 409:
        return 9
    return 10


@dataclass(frozen=True)
class SwissStanding:
    place: int
    participant_id: int
    user_id: int
    username: str | None
    display_name: str
    match_points: int
    wins: int
    losses: int
    draws: int
    byes: int
    opponents_match_win_percentage: float
    game_win_percentage: float
    opponents_game_win_percentage: float
    initial_rank: int

    @property
    def record(self) -> str:
        return f"{self.wins}–{self.losses}–{self.draws}"


@dataclass(frozen=True)
class SwissRoundResult:
    round_number: int
    planned_rounds: int
    matches: int
    bye_user_id: int | None


@dataclass
class _Stats:
    participant: models.Participant
    display_name: str
    match_points: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    byes: int = 0
    game_points: int = 0
    games_played: int = 0
    opponents: list[int] = field(default_factory=list)

    @property
    def match_win_percentage(self) -> float:
        rounds = self.wins + self.losses + self.draws
        actual = self.match_points / (rounds * 3) if rounds else 0.0
        return max(MIN_PERCENTAGE, actual)

    @property
    def game_win_percentage(self) -> float:
        actual = self.game_points / (self.games_played * 3) if self.games_played else 0.0
        return max(MIN_PERCENTAGE, actual)


@dataclass(frozen=True)
class _PairingPlayer:
    user_id: int
    place: int
    points: int
    up_floats: int
    down_floats: int
    last_float: str | None


class InternalSwissService:
    """Manage one tournament whose pairings are generated inside the bot."""

    def __init__(self, db: Session, *, rng: random.Random | None = None) -> None:
        self.db = db
        self.rng = rng or random.SystemRandom()
        self.users = UserService(db)
        self.results = RoundResultsService(db)

    def set_enabled(self, tournament_id: int, admin_tg_id: int, enabled: bool) -> models.Tournament:
        if not self.users.is_admin(admin_tg_id):
            raise RoundResultError("Нет прав администратора.")
        tournament = self._tournament(tournament_id, lock=True)
        if not tournament.is_online:
            raise RoundResultError("Внутренний Swiss пока доступен только для онлайн-турниров.")
        if tournament.status != models.TournamentStatus.REGISTRATION:
            raise RoundResultError("Режим турнира можно выбрать только до первого раунда.")
        has_pairings = self.db.execute(
            select(models.RoundPairing.id).where(models.RoundPairing.tournament_id == tournament_id).limit(1)
        ).scalar_one_or_none()
        if has_pairings is not None or tournament.aetherhub_url:
            raise RoundResultError("У турнира уже есть данные AetherHub или паринги; режим менять нельзя.")
        tournament.engine_mode = (
            models.TournamentEngineMode.INTERNAL_SWISS if enabled else models.TournamentEngineMode.AETHERHUB
        )
        tournament.swiss_rounds = None
        tournament.show_round_pairings = enabled
        self.db.commit()
        self.db.refresh(tournament)
        return tournament

    def generate_next_round(self, tournament_id: int, admin_tg_id: int) -> SwissRoundResult:
        if not self.users.is_admin(admin_tg_id):
            raise RoundResultError("Нет прав администратора.")
        tournament = self._tournament(tournament_id, lock=True)
        self._ensure_internal(tournament)
        participants = self._participants(tournament_id)
        if len(participants) < 2:
            raise RoundResultError("Для первого раунда нужны минимум два игрока.")

        current_round = self.results.latest_round_number(tournament_id)
        if current_round is None:
            if tournament.status != models.TournamentStatus.REGISTRATION:
                raise RoundResultError("Первый раунд уже нельзя создать в текущем статусе турнира.")
            self._assign_initial_ranks(participants)
            tournament.swiss_rounds = recommended_swiss_rounds(len(participants))
            tournament.status = models.TournamentStatus.ONGOING
            tournament.started_at = tournament.started_at or models.utc_now()
            tournament.show_round_pairings = True
            self.db.flush()
        else:
            if tournament.status != models.TournamentStatus.ONGOING:
                raise RoundResultError("Следующий раунд можно создать только в идущем турнире.")
            if not self._round_ready(tournament_id, current_round):
                raise RoundResultError(f"Сначала соберите все результаты раунда {current_round}.")
            if current_round >= (tournament.swiss_rounds or 0):
                raise RoundResultError("Все запланированные Swiss-раунды уже сыграны. Завершите турнир.")

        next_round = (current_round or 0) + 1
        standings = self.standings(tournament_id)
        pairs, bye_user_id = self._build_pairings(tournament_id, standings)
        by_user_id = {participant.user_id: participant for participant in participants}
        source_names = self._source_names(participants)

        for table_number, (left_id, right_id) in enumerate(pairs, start=1):
            left_name = source_names[left_id]
            right_name = source_names[right_id]
            self.db.add_all(
                [
                    models.RoundPairing(
                        tournament_id=tournament_id,
                        round_number=next_round,
                        table_number=table_number,
                        player_name=left_name,
                        opponent_name=right_name,
                        player_user_id=left_id,
                        opponent_user_id=right_id,
                    ),
                    models.RoundPairing(
                        tournament_id=tournament_id,
                        round_number=next_round,
                        table_number=table_number,
                        player_name=right_name,
                        opponent_name=left_name,
                        player_user_id=right_id,
                        opponent_user_id=left_id,
                    ),
                ]
            )
        if bye_user_id is not None:
            self.db.add(
                models.RoundPairing(
                    tournament_id=tournament_id,
                    round_number=next_round,
                    table_number=len(pairs) + 1,
                    player_name=source_names[bye_user_id],
                    opponent_name=None,
                    player_wins=2,
                    opponent_wins=0,
                    player_user_id=bye_user_id,
                    opponent_user_id=None,
                )
            )
        self.db.commit()

        # Exact user ids on RoundPairing avoid fuzzy-name resolution, including
        # when two registered players happen to have the same full name.
        matches = self.results.sync_round(tournament_id, next_round)
        return SwissRoundResult(
            round_number=next_round,
            planned_rounds=tournament.swiss_rounds or recommended_swiss_rounds(len(by_user_id)),
            matches=len(matches),
            bye_user_id=bye_user_id,
        )

    def finish(self, tournament_id: int, admin_tg_id: int) -> list[SwissStanding]:
        if not self.users.is_admin(admin_tg_id):
            raise RoundResultError("Нет прав администратора.")
        tournament = self._tournament(tournament_id, lock=True)
        self._ensure_internal(tournament)
        if tournament.status != models.TournamentStatus.ONGOING:
            raise RoundResultError("Завершить можно только идущий Swiss-турнир.")
        current_round = self.results.latest_round_number(tournament_id)
        if current_round is None:
            raise RoundResultError("В турнире ещё нет раундов.")
        if current_round < (tournament.swiss_rounds or 0):
            raise RoundResultError(
                f"Сыграно раундов: {current_round}/{tournament.swiss_rounds}. Сначала создайте оставшиеся."
            )
        if not self._round_ready(tournament_id, current_round):
            raise RoundResultError(f"Сначала соберите все результаты раунда {current_round}.")
        standings = self.standings(tournament_id)
        participants = {row.id: row for row in self._participants(tournament_id)}
        for row in standings:
            participants[row.participant_id].final_place = row.place
        tournament.status = models.TournamentStatus.CLOSED
        tournament.ended_at = models.utc_now()
        tournament.closed_by_tg_id = admin_tg_id
        self.db.commit()
        return standings

    def standings(self, tournament_id: int) -> list[SwissStanding]:
        tournament = self._tournament(tournament_id)
        self._ensure_internal(tournament)
        participants = self._participants(tournament_id)
        stats = {
            participant.user_id: _Stats(
                participant=participant,
                display_name=(
                    format_participant_name(participant.user.first_name, participant.user.last_name)
                    or (
                        f"@{participant.user.username}" if participant.user.username else f"Игрок {participant.user_id}"
                    )
                ),
            )
            for participant in participants
        }
        for match in self._matches(tournament_id):
            self._apply_match(stats, match)

        sortable: list[tuple[tuple[float | int, ...], _Stats, float, float, float]] = []
        for item in stats.values():
            omw = self._opponents_average(item.opponents, stats, "match")
            ogw = self._opponents_average(item.opponents, stats, "game")
            gw = item.game_win_percentage
            initial_rank = item.participant.swiss_initial_rank or 10**9
            key = (-item.match_points, -omw, -gw, -ogw, initial_rank, item.participant.id)
            sortable.append((key, item, omw, gw, ogw))
        sortable.sort(key=lambda value: value[0])

        result: list[SwissStanding] = []
        for place, (_key, item, omw, gw, ogw) in enumerate(sortable, start=1):
            user = item.participant.user
            result.append(
                SwissStanding(
                    place=place,
                    participant_id=item.participant.id,
                    user_id=item.participant.user_id,
                    username=user.username,
                    display_name=item.display_name,
                    match_points=item.match_points,
                    wins=item.wins,
                    losses=item.losses,
                    draws=item.draws,
                    byes=item.byes,
                    opponents_match_win_percentage=omw,
                    game_win_percentage=gw,
                    opponents_game_win_percentage=ogw,
                    initial_rank=item.participant.swiss_initial_rank or 10**9,
                )
            )
        return result

    def _build_pairings(
        self, tournament_id: int, standings: list[SwissStanding]
    ) -> tuple[list[tuple[int, int]], int | None]:
        previous_opponents, float_history = self._pairing_history(tournament_id)
        byes = {row.user_id: row.byes for row in standings}
        active = list(standings)
        bye_user_id = None
        if len(active) % 2:
            minimum_byes = min(byes[row.user_id] for row in active)
            eligible = [row for row in active if byes[row.user_id] == minimum_byes]
            bye = max(eligible, key=lambda row: row.place)
            bye_user_id = bye.user_id
            active.remove(bye)

        players = []
        for row in active:
            up, down, last = float_history.get(row.user_id, (0, 0, None))
            players.append(_PairingPlayer(row.user_id, row.place, row.match_points, up, down, last))
        pairs = self._minimum_cost_pairs(players, previous_opponents)
        pairs.sort(key=lambda pair: min(self._place(pair[0], players), self._place(pair[1], players)))
        normalized = []
        for left, right in pairs:
            if self._place(left, players) > self._place(right, players):
                left, right = right, left
            normalized.append((left, right))
        return normalized, bye_user_id

    def _minimum_cost_pairs(
        self, players: list[_PairingPlayer], previous_opponents: set[frozenset[int]]
    ) -> list[tuple[int, int]]:
        ordered = sorted(players, key=lambda player: player.place)
        if len(ordered) <= 18:
            return self._exact_pairs(ordered, previous_opponents)

        # Large beta events use the same local priorities without exponential
        # search.  A two-pair repair removes avoidable rematches afterwards.
        remaining = ordered[:]
        pairs: list[tuple[_PairingPlayer, _PairingPlayer]] = []
        while remaining:
            left = remaining.pop(0)
            right = min(remaining, key=lambda candidate: self._pair_cost(left, candidate, previous_opponents))
            remaining.remove(right)
            pairs.append((left, right))
        self._repair_rematches(pairs, previous_opponents)
        return [(left.user_id, right.user_id) for left, right in pairs]

    def _exact_pairs(
        self, players: list[_PairingPlayer], previous_opponents: set[frozenset[int]]
    ) -> list[tuple[int, int]]:
        size = len(players)

        @lru_cache(maxsize=None)
        def solve(mask: int) -> tuple[tuple[int, int, int, int, int], tuple[tuple[int, int], ...]]:
            if mask == 0:
                return (0, 0, 0, 0, 0), ()
            left_index = (mask & -mask).bit_length() - 1
            rest = mask ^ (1 << left_index)
            best = None
            candidate_mask = rest
            while candidate_mask:
                right_bit = candidate_mask & -candidate_mask
                right_index = right_bit.bit_length() - 1
                sub_cost, sub_pairs = solve(rest ^ right_bit)
                local = self._pair_cost(players[left_index], players[right_index], previous_opponents)
                combined = (
                    sub_cost[0] + local[0],
                    sub_cost[1] + local[1],
                    max(sub_cost[2], local[1]),
                    sub_cost[3] + local[2],
                    sub_cost[4] + local[3],
                )
                candidate = (combined, ((left_index, right_index),) + sub_pairs)
                if best is None or candidate[0] < best[0]:
                    best = candidate
                candidate_mask ^= right_bit
            assert best is not None
            return best

        _cost, index_pairs = solve((1 << size) - 1)
        return [(players[left].user_id, players[right].user_id) for left, right in index_pairs]

    def _pair_cost(
        self,
        left: _PairingPlayer,
        right: _PairingPlayer,
        previous_opponents: set[frozenset[int]],
    ) -> tuple[int, int, int, int]:
        rematch = int(frozenset((left.user_id, right.user_id)) in previous_opponents)
        gap = abs(left.points - right.points)
        float_penalty = 0
        if left.points != right.points:
            high, low = (left, right) if left.points > right.points else (right, left)
            float_penalty += max(0, high.down_floats - high.up_floats) * 2
            float_penalty += max(0, low.up_floats - low.down_floats) * 2
            float_penalty += 4 if high.last_float == "down" else 0
            float_penalty += 4 if low.last_float == "up" else 0
        return rematch, gap, float_penalty, abs(left.place - right.place)

    def _repair_rematches(
        self,
        pairs: list[tuple[_PairingPlayer, _PairingPlayer]],
        previous_opponents: set[frozenset[int]],
    ) -> None:
        def repeated(pair: tuple[_PairingPlayer, _PairingPlayer]) -> bool:
            return frozenset((pair[0].user_id, pair[1].user_id)) in previous_opponents

        for index, pair in enumerate(pairs):
            if not repeated(pair):
                continue
            a, b = pair
            for other_index in range(index + 1, len(pairs)):
                c, d = pairs[other_index]
                options = [((a, c), (b, d)), ((a, d), (b, c))]
                viable = [option for option in options if not repeated(option[0]) and not repeated(option[1])]
                if not viable:
                    continue
                replacement = min(
                    viable,
                    key=lambda option: (
                        self._pair_cost(*option[0], previous_opponents),
                        self._pair_cost(*option[1], previous_opponents),
                    ),
                )
                pairs[index], pairs[other_index] = replacement
                break

    def _pairing_history(
        self, tournament_id: int
    ) -> tuple[set[frozenset[int]], dict[int, tuple[int, int, str | None]]]:
        points = {participant.user_id: 0 for participant in self._participants(tournament_id)}
        previous: set[frozenset[int]] = set()
        history: dict[int, list[int | str | None]] = {user_id: [0, 0, None] for user_id in points}
        for match in self._matches(tournament_id):
            left = match.player1_user_id
            right = match.player2_user_id
            if right is None:
                if left in points:
                    points[left] += MATCH_WIN_POINTS
                continue
            if left not in points or right not in points or match.status not in FINAL_STATUSES:
                continue
            previous.add(frozenset((left, right)))
            if points[left] > points[right]:
                history[left][1] += 1
                history[left][2] = "down"
                history[right][0] += 1
                history[right][2] = "up"
            elif points[right] > points[left]:
                history[right][1] += 1
                history[right][2] = "down"
                history[left][0] += 1
                history[left][2] = "up"
            self._apply_match_points(points, match)
        return previous, {
            user_id: (int(value[0]), int(value[1]), value[2] if isinstance(value[2], str) else None)
            for user_id, value in history.items()
        }

    @staticmethod
    def _apply_match(stats: dict[int, _Stats], match: models.RoundMatch) -> None:
        left = stats.get(match.player1_user_id)
        if left is None:
            return
        if match.player2_user_id is None:
            left.wins += 1
            left.byes += 1
            left.match_points += MATCH_WIN_POINTS
            left.game_points += 6
            left.games_played += 2
            return
        right = stats.get(match.player2_user_id)
        if right is None or match.status not in FINAL_STATUSES:
            return
        left.opponents.append(match.player2_user_id)
        right.opponents.append(match.player1_user_id)
        left_wins = match.player1_wins or 0
        right_wins = match.player2_wins or 0
        if left_wins > right_wins:
            left.wins += 1
            right.losses += 1
            left.match_points += MATCH_WIN_POINTS
        elif right_wins > left_wins:
            right.wins += 1
            left.losses += 1
            right.match_points += MATCH_WIN_POINTS
        else:
            left.draws += 1
            right.draws += 1
            left.match_points += MATCH_DRAW_POINTS
            right.match_points += MATCH_DRAW_POINTS

        # The current result UI records game wins, not an explicit drawn-game
        # count. A tied match implies one unfinished/drawn game for MTR game
        # points; 0-0 remains at the official 0.33 percentage floor either way.
        drawn_games = 1 if left_wins == right_wins else 0
        games = left_wins + right_wins + drawn_games
        left.game_points += left_wins * 3 + drawn_games
        right.game_points += right_wins * 3 + drawn_games
        left.games_played += games
        right.games_played += games

    @staticmethod
    def _apply_match_points(points: dict[int, int], match: models.RoundMatch) -> None:
        left = match.player1_user_id
        right = match.player2_user_id
        if left not in points:
            return
        if right is None:
            points[left] += MATCH_WIN_POINTS
        elif right in points and match.status in FINAL_STATUSES:
            if match.player1_wins > match.player2_wins:
                points[left] += MATCH_WIN_POINTS
            elif match.player2_wins > match.player1_wins:
                points[right] += MATCH_WIN_POINTS
            else:
                points[left] += MATCH_DRAW_POINTS
                points[right] += MATCH_DRAW_POINTS

    @staticmethod
    def _opponents_average(opponents: list[int], stats: dict[int, _Stats], kind: str) -> float:
        if not opponents:
            return 0.0
        if kind == "match":
            values = [stats[user_id].match_win_percentage for user_id in opponents if user_id in stats]
        else:
            values = [stats[user_id].game_win_percentage for user_id in opponents if user_id in stats]
        return sum(values) / len(values) if values else 0.0

    def _assign_initial_ranks(self, participants: list[models.Participant]) -> None:
        if all(participant.swiss_initial_rank is not None for participant in participants):
            return
        shuffled = participants[:]
        self.rng.shuffle(shuffled)
        for rank, participant in enumerate(shuffled, start=1):
            participant.swiss_initial_rank = rank

    def _matches(self, tournament_id: int) -> list[models.RoundMatch]:
        return list(
            self.db.execute(
                select(models.RoundMatch)
                .where(models.RoundMatch.tournament_id == tournament_id)
                .order_by(models.RoundMatch.round_number, models.RoundMatch.table_number, models.RoundMatch.id)
            ).scalars()
        )

    def _round_ready(self, tournament_id: int, round_number: int) -> bool:
        matches = [match for match in self._matches(tournament_id) if match.round_number == round_number]
        return bool(matches) and all(
            match.player2_user_id is None or match.status in FINAL_STATUSES for match in matches
        )

    def _participants(self, tournament_id: int) -> list[models.Participant]:
        return list(
            self.db.execute(
                select(models.Participant)
                .options(joinedload(models.Participant.user))
                .where(models.Participant.tournament_id == tournament_id)
                .order_by(models.Participant.id)
            ).scalars()
        )

    @staticmethod
    def _source_names(participants: list[models.Participant]) -> dict[int, str]:
        bases: dict[int, str] = {}
        counts: dict[str, int] = {}
        for participant in participants:
            user = participant.user
            base = format_participant_name(user.first_name, user.last_name)
            base = base or (f"@{user.username}" if user.username else f"Игрок {participant.id}")
            bases[user.id] = base
            counts[base.casefold()] = counts.get(base.casefold(), 0) + 1
        return {
            user_id: (f"{base} [#{user_id}]" if counts[base.casefold()] > 1 else base)
            for user_id, base in bases.items()
        }

    def _tournament(self, tournament_id: int, *, lock: bool = False) -> models.Tournament:
        statement = select(models.Tournament).where(models.Tournament.id == tournament_id)
        if lock:
            statement = statement.with_for_update()
        tournament = self.db.execute(statement).scalar_one_or_none()
        if tournament is None:
            raise RoundResultError("Турнир не найден.")
        return tournament

    @staticmethod
    def _ensure_internal(tournament: models.Tournament) -> None:
        if tournament.engine_mode != models.TournamentEngineMode.INTERNAL_SWISS:
            raise RoundResultError("Для этого турнира используется AetherHub.")

    @staticmethod
    def _place(user_id: int, players: list[_PairingPlayer]) -> int:
        return next(player.place for player in players if player.user_id == user_id)
