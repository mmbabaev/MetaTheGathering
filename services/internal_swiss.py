"""Opt-in internal Swiss tournament engine.

The service deliberately writes the existing ``RoundPairing`` compatibility
rows and canonical ``RoundMatch`` rows.  Result reporting, exports, tournament
status and club pairing publication therefore keep using the same data path as
an AetherHub-backed online tournament.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
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
INTERNAL_SWISS_ROUNDS = 4
DRAFT_SWISS_ROUNDS = 3
MIN_SWISS_ROUNDS = 3
# Single-elimination playoff cut sizes supported after the Swiss rounds.
PLAYOFF_SIZES = (8, 16)


def recommended_swiss_rounds(player_count: int, *, large_format: bool = False) -> int:
    """Default Swiss round count for a field.

    Classic internal events keep the fixed INTERNAL_SWISS_ROUNDS. In the large
    format ceil(log2(count)) rounds are enough to produce an undefeated champion,
    so 50 players get 6 rounds and 100 get 7; small fields keep a 3-round floor.
    The announced value is frozen at round 1 and can be overridden by an admin.
    """
    if player_count < 2:
        return 0
    if large_format:
        return max(MIN_SWISS_ROUNDS, (player_count - 1).bit_length())
    return INTERNAL_SWISS_ROUNDS


def playoff_rounds(playoff_size: int) -> int:
    """Rounds in a single-elimination bracket of ``playoff_size`` teams.

    The last round always carries both the final and the 3rd–4th place match.
    """
    return playoff_size.bit_length() - 1 if playoff_size else 0


def bracket_seed_pairs(playoff_size: int) -> list[tuple[int, int]]:
    """Standard single-elimination bracket pairings ordered by bracket slot.

    Top 8:   (1,8) then (4,5), (2,7), (3,6).
    Top 16:  (1,16), (8,9), (4,13), (5,12), (2,15), (7,10), (3,14), (6,11).
    Winners of adjacent slots meet in the next round; the first seed of each pair
    is the better seed and plays first.
    """
    if playoff_size == 2:
        return [(1, 2)]
    half = playoff_size // 2
    result: list[tuple[int, int]] = []
    for low, high in bracket_seed_pairs(half):
        result.append((low, high + half))
        result.append((min(low + half, high), max(low + half, high)))
    return result


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
    dropped: bool

    @property
    def record(self) -> str:
        return f"{self.wins}–{self.losses}–{self.draws}"


@dataclass(frozen=True)
class SwissRoundResult:
    round_number: int
    planned_rounds: int
    matches: int
    bye_user_id: int | None


@dataclass(frozen=True)
class SwissSettings:
    tournament_id: int
    swiss_rounds: int | None
    recommended_swiss_rounds: int
    playoff_size: int | None
    active_players: int
    rounds_frozen: bool
    playoff_frozen: bool
    large_format: bool


@dataclass(frozen=True)
class DraftSeat:
    seat: int
    participant_id: int
    user_id: int
    display_name: str


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
        if enabled and tournament.registration_close_at is None:
            raise RoundResultError("Для внутреннего Swiss сначала укажите время начала турнира.")
        tournament.engine_mode = (
            models.TournamentEngineMode.INTERNAL_SWISS if enabled else models.TournamentEngineMode.AETHERHUB
        )
        tournament.swiss_rounds = None
        tournament.playoff_size = None
        tournament.show_round_pairings = enabled
        self.db.commit()
        self.db.refresh(tournament)
        return tournament

    def generate_draft_seating(self, tournament_id: int, actor_tg_id: int) -> list[DraftSeat]:
        tournament = self._tournament(tournament_id, lock=True)
        if not self.users.can_manage_tournament(actor_tg_id, tournament):
            raise RoundResultError("Нет прав организатора турнира.")
        self._ensure_internal(tournament)
        if not tournament.is_draft:
            raise RoundResultError("Рассадка доступна только для драфта.")
        if tournament.status != models.TournamentStatus.REGISTRATION:
            raise RoundResultError("Рассадку можно сформировать только до первого раунда.")
        participants = self._participants(tournament_id)
        if len(participants) < 2:
            raise RoundResultError("Для рассадки нужны минимум два игрока.")
        if tournament.draft_seating_generated_at is None:
            shuffled = participants[:]
            self.rng.shuffle(shuffled)
            for seat, participant in enumerate(shuffled, start=1):
                participant.draft_seat = seat
                participant.swiss_initial_rank = seat
            tournament.draft_seating_generated_at = models.utc_now()
            tournament.swiss_rounds = DRAFT_SWISS_ROUNDS
            self.db.commit()
            participants = shuffled
        else:
            participants.sort(key=lambda row: row.draft_seat or 10**9)
        return [
            DraftSeat(
                seat=participant.draft_seat or index,
                participant_id=participant.id,
                user_id=participant.user_id,
                display_name=(
                    format_participant_name(participant.user.first_name, participant.user.last_name)
                    or (f"@{participant.user.username}" if participant.user.username else f"Игрок {participant.id}")
                ),
            )
            for index, participant in enumerate(participants, start=1)
        ]

    def generate_next_round(self, tournament_id: int, admin_tg_id: int) -> SwissRoundResult:
        tournament = self._tournament(tournament_id, lock=True)
        if not self.users.can_manage_tournament(admin_tg_id, tournament):
            raise RoundResultError("Нет прав организатора турнира.")
        self._ensure_internal(tournament)
        participants = self._participants(tournament_id)
        if len(participants) < 2:
            raise RoundResultError("Для первого раунда нужны минимум два игрока.")

        current_round = self.results.latest_round_number(tournament_id)
        if current_round is None:
            if tournament.status != models.TournamentStatus.REGISTRATION:
                raise RoundResultError("Первый раунд уже нельзя создать в текущем статусе турнира.")
            if tournament.registration_close_at is None:
                raise RoundResultError("У турнира не указано время начала.")
            if tournament.is_draft and tournament.draft_seating_generated_at is None:
                raise RoundResultError("Сначала сформируйте рассадку игроков.")
            if any(participant.archetype_id is None for participant in participants) and not tournament.is_draft:
                raise RoundResultError("Перед первым раундом у всех игроков должен быть указан архетип.")
            if tournament.is_draft:
                if any(participant.draft_seat is None for participant in participants):
                    raise RoundResultError("Рассадка повреждена. Сформируйте её заново.")
                tournament.swiss_rounds = DRAFT_SWISS_ROUNDS
            else:
                self._assign_initial_ranks(participants)
                tournament.swiss_rounds = tournament.swiss_rounds or recommended_swiss_rounds(
                    len(participants), large_format=tournament.swiss_large_format
                )
            tournament.status = models.TournamentStatus.ONGOING
            tournament.started_at = tournament.started_at or models.utc_now()
            tournament.show_round_pairings = True
            self.db.flush()
        else:
            if tournament.status != models.TournamentStatus.ONGOING:
                raise RoundResultError("Следующий раунд можно создать только в идущем турнире.")
            if not self._round_ready(tournament_id, current_round):
                raise RoundResultError(f"Сначала соберите все результаты раунда {current_round}.")
            if current_round >= self.total_planned_rounds(tournament):
                raise RoundResultError("Все запланированные раунды уже сыграны. Завершите турнир.")

        next_round = (current_round or 0) + 1
        if tournament.is_draft and next_round == 1:
            pairs, bye_user_id = self._draft_first_round_pairings(participants)
        elif tournament.swiss_large_format and next_round > (tournament.swiss_rounds or 0):
            pairs, bye_user_id = self._playoff_pairings(tournament, next_round)
        else:
            standings = self.standings(tournament_id)
            pairs, bye_user_id = self._build_pairings(tournament_id, standings)
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
            planned_rounds=self.total_planned_rounds(tournament),
            matches=len(matches),
            bye_user_id=bye_user_id,
        )

    def set_swiss_large_format(self, tournament_id: int, admin_tg_id: int, enabled: bool) -> models.Tournament:
        """Switch the tournament between classic (4 rounds, no playoff) and large format.

        Only available before round 1 is generated; drafts always play classic.
        """
        if not self.users.is_admin(admin_tg_id):
            raise RoundResultError("Нет прав администратора.")
        tournament = self._tournament(tournament_id, lock=True)
        self._ensure_internal(tournament)
        if tournament.is_draft:
            raise RoundResultError("Драфт не поддерживает большой формат.")
        if self.results.latest_round_number(tournament_id) is not None:
            raise RoundResultError("Формат можно переключить только до первого раунда.")
        tournament.swiss_large_format = bool(enabled)
        if not enabled:
            tournament.swiss_rounds = None
            tournament.playoff_size = None
        self.db.commit()
        self.db.refresh(tournament)
        return tournament

    def set_swiss_rounds(self, tournament_id: int, admin_tg_id: int, rounds: int) -> models.Tournament:
        if not self.users.is_admin(admin_tg_id):
            raise RoundResultError("Нет прав администратора.")
        tournament = self._tournament(tournament_id, lock=True)
        self._ensure_internal(tournament)
        if not tournament.swiss_large_format:
            raise RoundResultError("Ручной выбор раундов доступен только в большом формате.")
        if tournament.is_draft:
            raise RoundResultError("Драфт всегда играет фиксированные три раунда.")
        if self.results.latest_round_number(tournament_id) is not None:
            raise RoundResultError("Число Swiss-раундов можно изменить только до первого раунда.")
        if not isinstance(rounds, int) or not MIN_SWISS_ROUNDS <= rounds <= 20:
            raise RoundResultError("Число Swiss-раундов — целое число от 3 до 20.")
        tournament.swiss_rounds = rounds
        self.db.commit()
        self.db.refresh(tournament)
        return tournament

    def set_playoff_size(self, tournament_id: int, admin_tg_id: int, size: int) -> models.Tournament:
        if not self.users.is_admin(admin_tg_id):
            raise RoundResultError("Нет прав администратора.")
        tournament = self._tournament(tournament_id, lock=True)
        self._ensure_internal(tournament)
        if not tournament.swiss_large_format:
            raise RoundResultError("Плей-офф доступен только в большом формате.")
        if tournament.is_draft:
            raise RoundResultError("Драфт не поддерживает плей-офф.")
        if size not in (0, *PLAYOFF_SIZES):
            raise RoundResultError("Варианты плей-оффа: без плей-оффа, топ-8 или топ-16.")
        if self._playoff_played(tournament):
            raise RoundResultError("Плей-офф уже начался, размер изменить нельзя.")
        tournament.playoff_size = size or None
        self.db.commit()
        self.db.refresh(tournament)
        return tournament

    def get_swiss_settings(self, tournament_id: int) -> SwissSettings:
        tournament = self._tournament(tournament_id)
        self._ensure_internal(tournament)
        active = len(self._participants(tournament_id))
        if tournament.is_draft:
            recommended = DRAFT_SWISS_ROUNDS
        else:
            recommended = recommended_swiss_rounds(active, large_format=tournament.swiss_large_format)
        return SwissSettings(
            tournament_id=tournament_id,
            swiss_rounds=tournament.swiss_rounds,
            recommended_swiss_rounds=recommended,
            playoff_size=tournament.playoff_size,
            active_players=active,
            rounds_frozen=self.results.latest_round_number(tournament_id) is not None,
            playoff_frozen=self._playoff_played(tournament),
            large_format=tournament.swiss_large_format,
        )

    def total_planned_rounds(self, tournament: models.Tournament) -> int:
        """Swiss rounds plus playoff rounds still scheduled for this tournament."""
        return (tournament.swiss_rounds or 0) + playoff_rounds(self.effective_playoff_size(tournament))

    def effective_playoff_size(self, tournament: models.Tournament) -> int:
        """Cut size that will actually happen: 0 when the field is too small or classic format."""
        if not tournament.swiss_large_format:
            return 0
        size = tournament.playoff_size or 0
        if size not in PLAYOFF_SIZES:
            return 0
        if self._playoff_played(tournament):
            return size
        if len(self._participants(tournament.id)) < size:
            return 0
        return size

    def playoff_round_label(self, tournament: models.Tournament, round_number: int) -> str | None:
        """Human label for a playoff round: "1/8 финала", "Финал и матч за 3-е место", ..."""
        playoff_index = round_number - (tournament.swiss_rounds or 0)
        if playoff_index <= 0:
            return None
        cut = tournament.playoff_size or self.effective_playoff_size(tournament)
        names = {
            8: ["Четвертьфинал", "Полуфинал", "Финал"],
            16: ["1/8 финала", "Четвертьфинал", "Полуфинал", "Финал"],
        }.get(cut, [])
        if not names or playoff_index > len(names):
            return None
        label = names[playoff_index - 1]
        if playoff_index == len(names):
            label = f"{label} и матч за 3-е место"
        return label

    def finish(self, tournament_id: int, admin_tg_id: int) -> list[SwissStanding]:
        tournament = self._tournament(tournament_id, lock=True)
        if not self.users.can_manage_tournament(
            admin_tg_id, tournament
        ) and not self.users.is_privileged_for_tournament(admin_tg_id, tournament):
            raise RoundResultError("Нет прав.")
        self._ensure_internal(tournament)
        if tournament.status != models.TournamentStatus.ONGOING:
            raise RoundResultError("Завершить можно только идущий Swiss-турнир.")
        current_round = self.results.latest_round_number(tournament_id)
        if current_round is None:
            raise RoundResultError("В турнире ещё нет раундов.")
        planned = self.total_planned_rounds(tournament)
        if current_round < planned:
            raise RoundResultError(f"Сыграно раундов: {current_round}/{planned}. Сначала создайте оставшиеся.")
        if not self._round_ready(tournament_id, current_round):
            raise RoundResultError(f"Сначала соберите все результаты раунда {current_round}.")
        standings = self.standings(tournament_id)
        if self.effective_playoff_size(tournament):
            standings = self._ranked_final_standings(tournament, standings)
        participants = {row.id: row for row in self._participants(tournament_id, include_dropped=True)}
        for row in standings:
            participants[row.participant_id].final_place = row.place
        tournament.status = models.TournamentStatus.CLOSED
        tournament.ended_at = models.utc_now()
        tournament.closed_by_tg_id = admin_tg_id
        self.db.commit()
        return standings

    @staticmethod
    def _draft_first_round_pairings(
        participants: list[models.Participant],
    ) -> tuple[list[tuple[int, int]], int | None]:
        ordered = sorted(participants, key=lambda row: row.draft_seat or 10**9)
        bye = ordered.pop() if len(ordered) % 2 else None
        half = len(ordered) // 2
        pairs = [(ordered[index].user_id, ordered[index + half].user_id) for index in range(half)]
        return pairs, bye.user_id if bye else None

    def standings(self, tournament_id: int) -> list[SwissStanding]:
        tournament = self._tournament(tournament_id)
        self._ensure_internal(tournament)
        participants = self._participants(tournament_id, include_dropped=True)
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
        swiss_rounds = tournament.swiss_rounds or 0
        for match in self._matches(tournament_id):
            if match.round_number > swiss_rounds:
                # Single-elimination playoff matches held after the Swiss rounds
                # must not feed the Swiss standings or their tiebreakers.
                continue
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
                    dropped=item.participant.dropped_at is not None,
                )
            )
        if tournament.status == models.TournamentStatus.CLOSED and self._playoff_played(tournament):
            return self._ranked_final_standings(tournament, result)
        return result

    def _playoff_pairings(self, tournament: models.Tournament, next_round: int) -> tuple[list[tuple[int, int]], None]:
        """Seed the bracket at round 1, then pair winners of adjacent slots.

        The better seed of each pair plays first. The last playoff round pairs the
        two semi-final winners in the final and the two losers for the 3rd place.
        """
        tournament_id = tournament.id
        swiss_rounds = tournament.swiss_rounds or 0
        cut = self.effective_playoff_size(tournament)
        if cut not in PLAYOFF_SIZES:
            raise RoundResultError("Плей-офф не настроен для этого турнира.")
        playoff_index = next_round - swiss_rounds
        participants = {row.user_id: row for row in self._participants(tournament_id, include_dropped=True)}

        if playoff_index == 1:
            active = [row for row in self.standings(tournament_id) if not row.dropped]
            if len(active) < cut:
                raise RoundResultError("В плей-офф выходят не больше игроков, чем зарегистрировано.")
            by_seed: dict[int, int] = {}
            for seed, row in enumerate(active[:cut], start=1):
                participants[row.user_id].playoff_seed = seed
                by_seed[seed] = row.user_id
            pairs = [(by_seed[first], by_seed[second]) for first, second in bracket_seed_pairs(cut)]
            return pairs, None

        previous_matches = self._matches(tournament_id, round_number=next_round - 1)
        winners = [self._match_winner(match) for match in previous_matches]
        if any(winner is None for winner in winners):
            raise RoundResultError("Результаты предыдущего раунда плей-оффа не готовы.")
        if playoff_index == playoff_rounds(cut):
            finalists = (
                self._match_winner(previous_matches[0]),
                self._match_winner(previous_matches[1]),
            )
            third_contenders = (
                self._match_loser(previous_matches[0]),
                self._match_loser(previous_matches[1]),
            )
            pairs_raw = [finalists, third_contenders]
        else:
            pairs_raw = [(winners[index], winners[index + 1]) for index in range(0, len(winners), 2)]
        by_seed_map = {row.user_id: row.playoff_seed for row in participants.values()}

        def seed_ordered(left: int, right: int) -> tuple[int, int]:
            return (left, right) if by_seed_map[left] <= by_seed_map[right] else (right, left)

        return [seed_ordered(left, right) for left, right in pairs_raw], None

    def _playoff_final_places(self, tournament: models.Tournament, standings: list[SwissStanding]) -> dict[int, int]:
        """Map every registered user to a final placement for a played playoff."""
        cut = self.effective_playoff_size(tournament)
        if cut not in PLAYOFF_SIZES:
            raise RoundResultError("Плей-офф не был сыгран.")
        swiss_rounds = tournament.swiss_rounds or 0
        playoff_total = playoff_rounds(cut)
        active = [row for row in standings if not row.dropped]
        if len(active) < cut:
            raise RoundResultError("Плей-офф не был сыгран.")
        cut_rows = active[:cut]
        cut_user_ids = {row.user_id for row in cut_rows}
        seed_map = {row.user_id: order for order, row in enumerate(cut_rows, start=1)}

        matches_by_round: dict[int, list[models.RoundMatch]] = {}
        for match in self._matches(tournament.id):
            if match.round_number > swiss_rounds:
                matches_by_round.setdefault(match.round_number, []).append(match)

        eliminated_in: dict[int, int] = {}
        for playoff_index in range(1, playoff_total):
            for match in matches_by_round.get(swiss_rounds + playoff_index, []):
                loser = self._match_loser(match)
                if loser is not None:
                    eliminated_in[loser] = playoff_index

        final_round = matches_by_round.get(swiss_rounds + playoff_total, [])
        if len(final_round) != 2:
            raise RoundResultError("Не удалось определить итоги плей-оффа.")
        finals = [
            match
            for match in final_round
            if match.player1_user_id not in eliminated_in and match.player2_user_id not in eliminated_in
        ]
        third_place = [match for match in final_round if match not in finals]
        if len(finals) != 1 or len(third_place) != 1:
            raise RoundResultError("Не удалось определить пары финального раунда.")
        champion = self._match_winner(finals[0])
        runner_up = self._match_loser(finals[0])
        third = self._match_winner(third_place[0])
        fourth = self._match_loser(third_place[0])
        if None in (champion, runner_up, third, fourth):
            raise RoundResultError("Не удалось определить победителя плей-оффа.")

        ordered: list[int] = [champion, runner_up, third, fourth]
        # Players eliminated in the earlier rounds share a tied place cut//2**r+1;
        # the tie is broken by Swiss standings (seed), so places are distinct.
        for playoff_index in range(playoff_total - 2, 0, -1):
            members = [user_id for user_id, index in eliminated_in.items() if index == playoff_index]
            members.sort(key=lambda user_id: seed_map[user_id])
            ordered.extend(members)

        places = {user_id: place for place, user_id in enumerate(ordered, start=1)}
        # Everyone outside the cut keeps their Swiss ranking, placed after the cut.
        for offset, row in enumerate((row for row in standings if row.user_id not in cut_user_ids), start=cut + 1):
            places[row.user_id] = offset
        return places

    def _ranked_final_standings(
        self, tournament: models.Tournament, standings: list[SwissStanding]
    ) -> list[SwissStanding]:
        """Rebuild Swiss standings rows in final placement order."""
        places = self._playoff_final_places(tournament, standings)
        by_user = {row.user_id: row for row in standings}
        ranked: list[SwissStanding] = []
        for user_id, place in sorted(places.items(), key=lambda item: item[1]):
            original = by_user.get(user_id)
            if original is not None:
                ranked.append(replace(original, place=place))
        return ranked

    @staticmethod
    def _match_winner(match: models.RoundMatch) -> int | None:
        if match.player2_user_id is None:
            return match.player1_user_id
        if (match.player1_wins or 0) > (match.player2_wins or 0):
            return match.player1_user_id
        if (match.player2_wins or 0) > (match.player1_wins or 0):
            return match.player2_user_id
        return None

    @staticmethod
    def _match_loser(match: models.RoundMatch) -> int | None:
        winner = InternalSwissService._match_winner(match)
        if winner is None:
            return None
        return match.player2_user_id if winner == match.player1_user_id else match.player1_user_id

    def _playoff_played(self, tournament: models.Tournament) -> bool:
        swiss_rounds = tournament.swiss_rounds or 0
        return any(match.round_number > swiss_rounds for match in self._matches(tournament.id))

    def _build_pairings(
        self, tournament_id: int, standings: list[SwissStanding]
    ) -> tuple[list[tuple[int, int]], int | None]:
        previous_opponents, float_history = self._pairing_history(tournament_id)
        byes = {row.user_id: row.byes for row in standings}
        active = [row for row in standings if not row.dropped]
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
        # search. A two-pair repair then tries to remove avoidable rematches.
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
        points = {participant.user_id: 0 for participant in self._participants(tournament_id, include_dropped=True)}
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

    def _matches(self, tournament_id: int, *, round_number: int | None = None) -> list[models.RoundMatch]:
        statement = (
            select(models.RoundMatch)
            .where(models.RoundMatch.tournament_id == tournament_id)
            .order_by(models.RoundMatch.round_number, models.RoundMatch.table_number, models.RoundMatch.id)
        )
        if round_number is not None:
            statement = statement.where(models.RoundMatch.round_number == round_number)
        return list(self.db.execute(statement).scalars())

    def _round_ready(self, tournament_id: int, round_number: int) -> bool:
        matches = self._matches(tournament_id, round_number=round_number)
        return bool(matches) and all(
            match.player2_user_id is None or match.status in FINAL_STATUSES for match in matches
        )

    def _participants(self, tournament_id: int, *, include_dropped: bool = False) -> list[models.Participant]:
        conditions = [models.Participant.tournament_id == tournament_id]
        if not include_dropped:
            conditions.append(models.Participant.dropped_at.is_(None))
        return list(
            self.db.execute(
                select(models.Participant)
                .options(joinedload(models.Participant.user))
                .where(*conditions)
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
