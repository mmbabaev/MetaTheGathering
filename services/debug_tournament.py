"""Safe debug-only AetherHub-like tournament simulator."""

from __future__ import annotations

import random
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models
from services.names import format_participant_name
from services.round_results import FINAL_STATUSES, RoundResultError, RoundResultsService
from services.user import UserService

DEBUG_PLAYER_TARGET = 15
_DEBUG_SCORES = ((2, 0), (2, 1), (1, 0), (1, 1), (0, 0), (0, 1), (0, 2), (1, 2))


@dataclass(frozen=True)
class DebugFillResult:
    added: int
    total: int


@dataclass(frozen=True)
class DebugRoundResult:
    round_number: int
    matches: int
    completed_previous: int


class DebugTournamentService:
    def __init__(self, db: Session, *, rng: random.Random | None = None) -> None:
        self.db = db
        self.rng = rng or random.Random()
        self.users = UserService(db)
        self.results = RoundResultsService(db)

    def fill_to_15(self, tournament_id: int) -> DebugFillResult:
        tournament = self._tournament(tournament_id)
        participants = self._participants(tournament_id)
        to_add = max(0, DEBUG_PLAYER_TARGET - len(participants))
        next_tg_id = self.db.execute(select(func.min(models.User.tg_id)).where(models.User.tg_id < 0)).scalar()
        next_tg_id = min(next_tg_id or -9_000_000, -9_000_000) - 1

        # A removed debug participant may leave its synthetic User behind. Avoid
        # reusing that visible identity when the tournament is filled again.
        existing_debug_users = list(
            self.db.execute(
                select(models.User).where(models.User.username.like(f"debug_t{tournament_id}_p%"))
            ).scalars()
        )
        used_names = {(user.last_name or "").casefold() for user in existing_debug_users}
        used_names.update(
            (participant.user.last_name or "").casefold()
            for participant in participants
            if participant.user is not None
        )
        number = 1
        for _ in range(to_add):
            while f"Тестовый{number:02}".casefold() in used_names:
                number += 1
            last_name = f"Тестовый{number:02}"
            user = models.User(
                tg_id=next_tg_id,
                username=f"debug_t{tournament_id}_p{number:02}",
                first_name="Игрок",
                last_name=last_name,
            )
            self.db.add(user)
            self.db.flush()
            self.db.add(
                models.Participant(
                    tournament_id=tournament_id,
                    user_id=user.id,
                    added_by_admin=True,
                )
            )
            used_names.add(last_name.casefold())
            next_tg_id -= 1
            number += 1

        tournament.is_online = True
        tournament.show_round_pairings = True
        self.db.commit()
        return DebugFillResult(added=to_add, total=len(self._participants(tournament_id)))

    def next_round(self, tournament_id: int, admin_tg_id: int) -> DebugRoundResult:
        tournament = self._tournament(tournament_id)
        if not self.users.is_admin(admin_tg_id):
            raise RoundResultError("Нет прав администратора.")
        participants = self._participants(tournament_id)
        if len(participants) < 2:
            raise RoundResultError("Сначала добавьте минимум двух игроков.")

        current_round = self.results.latest_round_number(tournament_id)
        completed = self._complete_round_randomly(tournament_id, current_round, admin_tg_id) if current_round else 0
        next_round = (current_round or 0) + 1
        points, previous_opponents, byes = self._standings(tournament_id)
        pairs, bye_user_id = self._pair_players(participants, points, previous_opponents, byes)

        user_by_id = {participant.user_id: participant.user for participant in participants}
        for table_number, (left_id, right_id) in enumerate(pairs, start=1):
            left_name = self._name(user_by_id[left_id])
            right_name = self._name(user_by_id[right_id])
            self.db.add_all(
                [
                    models.RoundPairing(
                        tournament_id=tournament_id,
                        round_number=next_round,
                        table_number=table_number,
                        player_name=left_name,
                        opponent_name=right_name,
                    ),
                    models.RoundPairing(
                        tournament_id=tournament_id,
                        round_number=next_round,
                        table_number=table_number,
                        player_name=right_name,
                        opponent_name=left_name,
                    ),
                ]
            )
        if bye_user_id is not None:
            self.db.add(
                models.RoundPairing(
                    tournament_id=tournament_id,
                    round_number=next_round,
                    table_number=len(pairs) + 1,
                    player_name=self._name(user_by_id[bye_user_id]),
                    opponent_name=None,
                )
            )
        tournament.is_online = True
        tournament.show_round_pairings = True
        tournament.status = models.TournamentStatus.ONGOING
        if tournament.started_at is None:
            tournament.started_at = models.utc_now()
        self.db.commit()

        direct_users = {self._name(user): user for user in user_by_id.values()}
        matches = self.results.sync_round(
            tournament_id,
            next_round,
            find_user=lambda name: direct_users.get(name),
        )
        return DebugRoundResult(
            round_number=next_round,
            matches=len(matches),
            completed_previous=completed,
        )

    def _complete_round_randomly(self, tournament_id: int, round_number: int, admin_tg_id: int) -> int:
        completed = 0
        for match in self.results.list_round(tournament_id, round_number):
            if match.player2_name is None or match.status in FINAL_STATUSES:
                continue
            left, right = self.rng.choice(_DEBUG_SCORES)
            self.results.admin_set(match.id, admin_tg_id, left, right)
            completed += 1
        return completed

    def _standings(self, tournament_id: int) -> tuple[dict[int, int], set[frozenset[int]], set[int]]:
        participants = self._participants(tournament_id)
        points = {participant.user_id: 0 for participant in participants}
        opponents: set[frozenset[int]] = set()
        byes: set[int] = set()
        for match in self.results.sync_tournament(tournament_id):
            if match.player2_name is None:
                if match.player1_user_id in points:
                    points[match.player1_user_id] += 3
                    byes.add(match.player1_user_id)
                continue
            if match.status not in FINAL_STATUSES or match.player1_user_id is None or match.player2_user_id is None:
                continue
            opponents.add(frozenset((match.player1_user_id, match.player2_user_id)))
            if match.player1_wins > match.player2_wins:
                points[match.player1_user_id] += 3
            elif match.player2_wins > match.player1_wins:
                points[match.player2_user_id] += 3
            else:
                points[match.player1_user_id] += 1
                points[match.player2_user_id] += 1
        return points, opponents, byes

    def _pair_players(
        self,
        participants: list[models.Participant],
        points: dict[int, int],
        previous_opponents: set[frozenset[int]],
        byes: set[int],
    ) -> tuple[list[tuple[int, int]], int | None]:
        user_ids = [participant.user_id for participant in participants]
        self.rng.shuffle(user_ids)
        user_ids.sort(key=lambda user_id: -points.get(user_id, 0))

        bye_user_id = None
        if len(user_ids) % 2:
            eligible = [user_id for user_id in user_ids if user_id not in byes] or user_ids
            lowest = min(points.get(user_id, 0) for user_id in eligible)
            candidates = [user_id for user_id in eligible if points.get(user_id, 0) == lowest]
            bye_user_id = self.rng.choice(candidates)
            user_ids.remove(bye_user_id)

        pairs: list[tuple[int, int]] = []
        while user_ids:
            left = user_ids.pop(0)
            ranked = sorted(
                enumerate(user_ids),
                key=lambda item: (
                    abs(points.get(left, 0) - points.get(item[1], 0)),
                    frozenset((left, item[1])) in previous_opponents,
                    self.rng.random(),
                ),
            )
            right_index, right = ranked[0]
            user_ids.pop(right_index)
            pairs.append((left, right))
        return pairs, bye_user_id

    def _tournament(self, tournament_id: int) -> models.Tournament:
        tournament = self.db.get(models.Tournament, tournament_id)
        if tournament is None:
            raise RoundResultError("Турнир не найден.")
        if tournament.status == models.TournamentStatus.CLOSED:
            raise RoundResultError("Закрытый турнир нельзя менять debug-генератором.")
        return tournament

    def _participants(self, tournament_id: int) -> list[models.Participant]:
        return list(
            self.db.execute(
                select(models.Participant)
                .where(models.Participant.tournament_id == tournament_id)
                .order_by(models.Participant.id)
            ).scalars()
        )

    @staticmethod
    def _name(user: models.User) -> str:
        return format_participant_name(user.first_name, user.last_name) or f"debug-{user.id}"
