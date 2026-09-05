"""Peer-confirmed results for online tournament rounds.

``RoundPairing`` remains the imported/exported compatibility model (two reciprocal
rows per table). ``RoundMatch`` is the canonical one-row match used by the result
state machine. Confirmed/admin/imported scores are mirrored back to both pairing
rows so existing exports and standings keep working.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models
from services.user import UserService

FINAL_STATUSES = {
    models.RoundMatchStatus.CONFIRMED,
    models.RoundMatchStatus.ADMIN,
    models.RoundMatchStatus.IMPORTED,
}


class RoundResultError(ValueError):
    """A safe, user-facing round result validation error."""


@dataclass(frozen=True)
class RejectionResult:
    match: models.RoundMatch
    proposer_tg_id: int | None


class RoundResultsService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserService(db)

    @staticmethod
    def pairing_key(player1_name: str, player2_name: str | None) -> str:
        parts = sorted(
            value.strip().casefold().replace("ё", "е") for value in (player1_name, player2_name or "__bye__")
        )
        return hashlib.sha256("\0".join(parts).encode()).hexdigest()

    @staticmethod
    def validate_score(player1_wins: int, player2_wins: int) -> None:
        if player1_wins not in (0, 1, 2) or player2_wins not in (0, 1, 2):
            raise RoundResultError("Количество побед должно быть от 0 до 2.")
        if player1_wins == 2 and player2_wins == 2:
            raise RoundResultError("Счёт 2–2 невозможен.")

    def latest_round_number(self, tournament_id: int) -> int | None:
        return self.db.execute(
            select(func.max(models.RoundPairing.round_number)).where(models.RoundPairing.tournament_id == tournament_id)
        ).scalar_one_or_none()

    def sync_tournament(self, tournament_id: int) -> list[models.RoundMatch]:
        rounds = self.db.execute(
            select(models.RoundPairing.round_number)
            .where(models.RoundPairing.tournament_id == tournament_id)
            .distinct()
            .order_by(models.RoundPairing.round_number)
        ).scalars()
        result: list[models.RoundMatch] = []
        for round_number in rounds:
            result.extend(self.sync_round(tournament_id, round_number, commit=False))
        self.db.commit()
        return result

    def sync_round(
        self,
        tournament_id: int,
        round_number: int,
        *,
        find_user: Callable[[str], models.User | None] | None = None,
        commit: bool = True,
    ) -> list[models.RoundMatch]:
        """Create/update canonical matches from reciprocal imported pairing rows."""
        tournament = self.db.get(models.Tournament, tournament_id)
        if tournament is None:
            raise RoundResultError("Турнир не найден.")

        pairings = self.db.execute(
            select(models.RoundPairing)
            .where(
                models.RoundPairing.tournament_id == tournament_id,
                models.RoundPairing.round_number == round_number,
            )
            .order_by(models.RoundPairing.table_number, models.RoundPairing.id)
        ).scalars()
        resolver = find_user or self._default_user_resolver(tournament_id)
        seen: set[str] = set()
        result: list[models.RoundMatch] = []
        for pairing in pairings:
            key = self.pairing_key(pairing.player_name, pairing.opponent_name)
            if key in seen:
                continue
            seen.add(key)
            match = self.db.execute(
                select(models.RoundMatch).where(
                    models.RoundMatch.tournament_id == tournament_id,
                    models.RoundMatch.round_number == round_number,
                    models.RoundMatch.pairing_key == key,
                )
            ).scalar_one_or_none()
            if match is None:
                player1 = (
                    self.db.get(models.User, pairing.player_user_id)
                    if pairing.player_user_id is not None
                    else resolver(pairing.player_name)
                )
                player2 = (
                    self.db.get(models.User, pairing.opponent_user_id)
                    if pairing.opponent_user_id is not None
                    else resolver(pairing.opponent_name)
                    if pairing.opponent_name
                    else None
                )
                match = models.RoundMatch(
                    tournament_id=tournament_id,
                    round_number=round_number,
                    table_number=pairing.table_number,
                    pairing_key=key,
                    player1_name=pairing.player_name,
                    player2_name=pairing.opponent_name,
                    player1_user_id=player1.id if player1 else None,
                    player2_user_id=player2.id if player2 else None,
                    status=(
                        models.RoundMatchStatus.IMPORTED
                        if pairing.opponent_name is None
                        or (pairing.player_wins is not None and pairing.opponent_wins is not None)
                        else models.RoundMatchStatus.UNREPORTED
                    ),
                    player1_wins=pairing.player_wins,
                    player2_wins=pairing.opponent_wins,
                )
                self.db.add(match)
                self.db.flush()
            else:
                match.table_number = pairing.table_number
                if match.player1_user_id is None:
                    user = (
                        self.db.get(models.User, pairing.player_user_id)
                        if pairing.player_user_id is not None
                        else resolver(match.player1_name)
                    )
                    match.player1_user_id = user.id if user else None
                if match.player2_name and match.player2_user_id is None:
                    user = (
                        self.db.get(models.User, pairing.opponent_user_id)
                        if pairing.opponent_user_id is not None
                        else resolver(match.player2_name)
                    )
                    match.player2_user_id = user.id if user else None
                if (
                    match.status == models.RoundMatchStatus.UNREPORTED
                    and pairing.player_wins is not None
                    and pairing.opponent_wins is not None
                ):
                    match.player1_wins = pairing.player_wins
                    match.player2_wins = pairing.opponent_wins
                    match.status = models.RoundMatchStatus.IMPORTED
                    match.revision += 1
                    self._add_event(match, "imported", None)

            if match.status in FINAL_STATUSES and match.player2_name is not None:
                self._write_pairing_score(match)
            result.append(match)

        if commit:
            self.db.commit()
        return result

    def _default_user_resolver(self, tournament_id: int) -> Callable[[str], models.User | None]:
        tournament = self.db.get(models.Tournament, tournament_id)

        def resolve(name: str) -> models.User | None:
            # Compatible with the pending Endstep-profile work without depending on
            # its branch: once UserService exposes the getter, online handles resolve here.
            get_by_endstep = getattr(self.users, "get_by_endstep_username", None)
            if tournament is not None and tournament.is_online and get_by_endstep is not None:
                user = get_by_endstep(name)
                if user is not None:
                    return user
            return self.users.resolve_and_merge_import_name(name)

        return resolve

    def list_round(self, tournament_id: int, round_number: int | None = None) -> list[models.RoundMatch]:
        round_number = round_number or self.latest_round_number(tournament_id)
        if round_number is None:
            return []
        self.sync_round(tournament_id, round_number)
        return list(
            self.db.execute(
                select(models.RoundMatch)
                .where(
                    models.RoundMatch.tournament_id == tournament_id,
                    models.RoundMatch.round_number == round_number,
                )
                .order_by(models.RoundMatch.table_number, models.RoundMatch.id)
            ).scalars()
        )

    def get_match(self, match_id: int, *, lock: bool = False) -> models.RoundMatch:
        statement = select(models.RoundMatch).where(models.RoundMatch.id == match_id)
        if lock:
            statement = statement.with_for_update()
        match = self.db.execute(statement).scalar_one_or_none()
        if match is None:
            raise RoundResultError("Матч не найден.")
        return match

    def current_match_for_user(self, tournament_id: int, tg_id: int) -> models.RoundMatch:
        tournament = self.db.get(models.Tournament, tournament_id)
        if tournament is None:
            raise RoundResultError("Турнир не найден.")
        if not tournament.is_online:
            raise RoundResultError("Сбор результатов доступен только для онлайн-турниров.")
        if tournament.status == models.TournamentStatus.CLOSED:
            raise RoundResultError("Турнир уже завершён.")
        round_number = self.latest_round_number(tournament_id)
        if round_number is None:
            raise RoundResultError("Паринги текущего раунда ещё не загружены.")
        self.sync_round(tournament_id, round_number)
        user = self.users.get_by_tg_id(tg_id)
        if user is None:
            raise RoundResultError("Вы не зарегистрированы в турнире.")
        match = self.db.execute(
            select(models.RoundMatch).where(
                models.RoundMatch.tournament_id == tournament_id,
                models.RoundMatch.round_number == round_number,
                (models.RoundMatch.player1_user_id == user.id) | (models.RoundMatch.player2_user_id == user.id),
            )
        ).scalar_one_or_none()
        if match is None:
            raise RoundResultError("Вы не найдены в парингах текущего раунда.")
        return match

    def score_from_actor(
        self, match: models.RoundMatch, actor_user_id: int, own_wins: int, opponent_wins: int
    ) -> tuple[int, int]:
        self.validate_score(own_wins, opponent_wins)
        if actor_user_id == match.player1_user_id:
            return own_wins, opponent_wins
        if actor_user_id == match.player2_user_id:
            return opponent_wins, own_wins
        raise RoundResultError("Этот матч не принадлежит вам.")

    def propose(self, match_id: int, actor_tg_id: int, own_wins: int, opponent_wins: int) -> models.RoundMatch:
        actor = self.users.get_by_tg_id(actor_tg_id)
        if actor is None:
            raise RoundResultError("Пользователь не найден.")
        match = self.get_match(match_id, lock=True)
        tournament = self.db.get(models.Tournament, match.tournament_id)
        if tournament is None or not tournament.is_online or tournament.status == models.TournamentStatus.CLOSED:
            raise RoundResultError("Сейчас результат этого матча изменить нельзя.")
        p1_wins, p2_wins = self.score_from_actor(match, actor.id, own_wins, opponent_wins)
        if match.player2_name is None:
            raise RoundResultError("Для bye результат вводить не нужно.")
        if match.status in FINAL_STATUSES:
            raise RoundResultError("Результат уже подтверждён. Изменить его может администратор.")
        if match.status == models.RoundMatchStatus.PENDING:
            raise RoundResultError("Результат уже отправлен сопернику на подтверждение.")
        match.player1_wins = p1_wins
        match.player2_wins = p2_wins
        match.status = models.RoundMatchStatus.PENDING
        match.proposed_by_user_id = actor.id
        match.confirmed_by_user_id = None
        match.revision += 1
        self._add_event(match, "proposed", actor)
        self.db.commit()
        self.db.refresh(match)
        return match

    def confirm(self, match_id: int, revision: int, actor_tg_id: int) -> models.RoundMatch:
        actor = self.users.get_by_tg_id(actor_tg_id)
        if actor is None:
            raise RoundResultError("Пользователь не найден.")
        match = self.get_match(match_id, lock=True)
        self._validate_response(match, revision, actor.id)
        match.status = models.RoundMatchStatus.CONFIRMED
        match.confirmed_by_user_id = actor.id
        self._add_event(match, "confirmed", actor)
        self._write_pairing_score(match)
        self.db.commit()
        self.db.refresh(match)
        return match

    def reject(self, match_id: int, revision: int, actor_tg_id: int) -> RejectionResult:
        actor = self.users.get_by_tg_id(actor_tg_id)
        if actor is None:
            raise RoundResultError("Пользователь не найден.")
        match = self.get_match(match_id, lock=True)
        self._validate_response(match, revision, actor.id)
        proposer = self.db.get(models.User, match.proposed_by_user_id) if match.proposed_by_user_id else None
        self._add_event(match, "rejected", actor)
        match.status = models.RoundMatchStatus.UNREPORTED
        match.player1_wins = None
        match.player2_wins = None
        match.proposed_by_user_id = None
        match.confirmed_by_user_id = None
        match.revision += 1
        self.db.commit()
        self.db.refresh(match)
        return RejectionResult(match=match, proposer_tg_id=proposer.tg_id if proposer and proposer.tg_id > 0 else None)

    def _validate_response(self, match: models.RoundMatch, revision: int, actor_user_id: int) -> None:
        if match.status != models.RoundMatchStatus.PENDING or match.revision != revision:
            raise RoundResultError("Это предложение уже неактуально.")
        if match.proposed_by_user_id == actor_user_id:
            raise RoundResultError("Подтвердить результат должен соперник.")
        if actor_user_id not in (match.player1_user_id, match.player2_user_id):
            raise RoundResultError("Этот матч не принадлежит вам.")

    def admin_set(self, match_id: int, admin_tg_id: int, player1_wins: int, player2_wins: int) -> models.RoundMatch:
        if not self.users.is_admin(admin_tg_id):
            raise RoundResultError("Нет прав администратора.")
        self.validate_score(player1_wins, player2_wins)
        match = self.get_match(match_id, lock=True)
        if match.player2_name is None:
            raise RoundResultError("Для bye результат вводить не нужно.")
        actor = self.users.get_by_tg_id(admin_tg_id)
        match.player1_wins = player1_wins
        match.player2_wins = player2_wins
        match.status = models.RoundMatchStatus.ADMIN
        match.proposed_by_user_id = None
        match.confirmed_by_user_id = actor.id if actor else None
        match.revision += 1
        self._add_event(match, "admin_set", actor, actor_tg_id=admin_tg_id)
        self._write_pairing_score(match)
        self.db.commit()
        self.db.refresh(match)
        return match

    def set_pairings_view(self, tournament_id: int, admin_tg_id: int, enabled: bool | None = None) -> bool:
        if not self.users.is_admin(admin_tg_id):
            raise RoundResultError("Нет прав администратора.")
        tournament = self.db.get(models.Tournament, tournament_id)
        if tournament is None:
            raise RoundResultError("Турнир не найден.")
        if not tournament.is_online:
            raise RoundResultError("Режим парингов доступен только для онлайн-турниров.")
        tournament.show_round_pairings = not tournament.show_round_pairings if enabled is None else enabled
        self.db.commit()
        return tournament.show_round_pairings

    def is_round_ready(self, tournament_id: int, round_number: int | None = None) -> bool:
        matches = self.list_round(tournament_id, round_number)
        return bool(matches) and all(match.player2_name is None or match.status in FINAL_STATUSES for match in matches)

    def _write_pairing_score(self, match: models.RoundMatch) -> None:
        for pairing in self.db.execute(
            select(models.RoundPairing).where(
                models.RoundPairing.tournament_id == match.tournament_id,
                models.RoundPairing.round_number == match.round_number,
                models.RoundPairing.player_name.in_([match.player1_name, match.player2_name]),
            )
        ).scalars():
            if pairing.player_name == match.player1_name:
                pairing.player_wins = match.player1_wins
                pairing.opponent_wins = match.player2_wins
            elif pairing.player_name == match.player2_name:
                pairing.player_wins = match.player2_wins
                pairing.opponent_wins = match.player1_wins

    def _add_event(
        self,
        match: models.RoundMatch,
        event_type: str,
        actor: models.User | None,
        *,
        actor_tg_id: int | None = None,
    ) -> None:
        self.db.add(
            models.RoundMatchEvent(
                match=match,
                event_type=event_type,
                actor_user_id=actor.id if actor else None,
                actor_tg_id=actor.tg_id if actor else actor_tg_id,
                player1_wins=match.player1_wins,
                player2_wins=match.player2_wins,
                revision=match.revision,
            )
        )
