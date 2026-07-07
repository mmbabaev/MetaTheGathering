from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from services import errors
from services.aetherhub_models import AetherhubRound, AetherhubTournamentData
from services.user import UserService


@dataclass
class ImportResult:
    registered: int  # new participants registered (matched or created)
    already_registered: int
    pairings_saved: int
    created_names: list[str]  # players not found in bot — created as placeholders
    new_round_numbers: list[int]  # rounds that appeared for the first time in this import


@dataclass
class OpponentInfo:
    round_number: int
    opponent_name: str | None  # None = bye
    opponent_user: models.User | None
    opponent_participant: models.Participant | None


def _participant_sort_key(p) -> tuple[str, str]:
    """Стабильный ключ сортировки участника по (фамилия, имя) в нижнем регистре."""
    u = getattr(p, "user", None)
    return ((u.last_name or "").lower(), (u.first_name or "").lower()) if u else ("", "")


@dataclass
class UnfilledOpponent:
    """Оппонент игрока без записанной колоды + раунд, в котором игрок с ним встречался."""

    participant: models.Participant
    round_number: int


@dataclass
class UndefeatedPlayer:
    """Игрок, прошедший турнир без поражений (X-0). Имя/фамилия из User, если найден."""

    player_name: str  # имя как в парингах AetherHub (фолбэк для отображения)
    first_name: str | None
    last_name: str | None
    archetype_name: str | None  # колода участника; None = не записана / игрок не найден
    final_place: int | None
    wins: int


class AetherhubImportService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._user_svc = UserService(db)

    def _normalize_import_name(self, full_name: str) -> str:
        """Normalize names coming from Aetherhub before matching users."""
        # Strip "(N Points)" inserted inside the name label; do it case-insensitively.
        s = re.sub(r"\(\s*\d+\s*points?\s*\)", "", full_name or "", flags=re.IGNORECASE)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def find_user_by_name(self, full_name: str) -> models.User | None:
        """Match full_name against User records using flexible name matching
        (both orderings, case-insensitive, ё/е normalization)."""
        full_name = self._normalize_import_name(full_name)
        if not full_name:
            return None
        return self._user_svc.find_by_name(full_name)

    def get_unfilled_opponents(
        self, tournament_id: int, user_id: int, participants: list
    ) -> tuple[list[UnfilledOpponent], str | None]:
        """Return (unfilled_opponents, error_key), sorted by the round they were played in.

        Each item is an ``UnfilledOpponent`` (participant + ``round_number``) so the UI
        can show «в каком туре» игрок встречался с оппонентом и разложить их по порядку.

        error_key is None on success, or one of:
          'no_pairings'     — no pairings imported for tournament
          'not_in_pairings' — user not found among pairing player names
          'all_filled'      — all opponents already have archetypes

        Builds name→User cache to avoid O(n²) queries.
        """
        pairings = self.get_pairings(tournament_id)
        if not pairings:
            return [], "no_pairings"

        all_names = {p.player_name for p in pairings} | {p.opponent_name for p in pairings if p.opponent_name}
        name_to_user: dict[str, models.User | None] = {}
        for name in all_names:
            name_to_user[name] = self.find_user_by_name(name)

        # раунд, в котором наш игрок встречался с каждым оппонентом (по имени из пейрингов);
        # при повторной встрече берём самый ранний раунд
        opp_round_by_name: dict[str, int] = {}
        for p in pairings:
            u = name_to_user.get(p.player_name)
            if u and u.id == user_id and p.opponent_name:
                prev = opp_round_by_name.get(p.opponent_name)
                if prev is None or p.round_number < prev:
                    opp_round_by_name[p.opponent_name] = p.round_number

        if not opp_round_by_name:
            return [], "not_in_pairings"

        opp_round_by_user: dict[int, int] = {}
        for opp_name, rnd in opp_round_by_name.items():
            u = name_to_user.get(opp_name)
            if u:
                prev = opp_round_by_user.get(u.id)
                if prev is None or rnd < prev:
                    opp_round_by_user[u.id] = rnd

        result = [
            UnfilledOpponent(participant=p, round_number=opp_round_by_user[p.user_id])
            for p in participants
            if p.archetype is None and p.user_id in opp_round_by_user
        ]
        result.sort(key=lambda o: (o.round_number, _participant_sort_key(o.participant)))
        return result, (None if result else "all_filled")

    def _get_or_create_user_by_name(self, full_name: str) -> tuple[models.User, bool]:
        """Find or create a user by full name. Returns (user, was_created)."""
        parts = full_name.strip().split(None, 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else None
        return self._user_svc.get_or_create_by_name(first_name, last_name)

    def _get_participant(self, tournament_id: int, user_id: int) -> models.Participant | None:
        return self.db.execute(
            select(models.Participant).where(
                models.Participant.tournament_id == tournament_id,
                models.Participant.user_id == user_id,
            )
        ).scalar_one_or_none()

    def _save_pairings(self, tournament_id: int, rounds: list[AetherhubRound]) -> int:
        saved = 0
        for rnd in rounds:
            for pairing in rnd.pairings:
                existing = self.db.execute(
                    select(models.RoundPairing).where(
                        models.RoundPairing.tournament_id == tournament_id,
                        models.RoundPairing.round_number == rnd.number,
                        models.RoundPairing.player_name == pairing.player,
                    )
                ).scalar_one_or_none()
                if existing is None:
                    self.db.add(
                        models.RoundPairing(
                            tournament_id=tournament_id,
                            round_number=rnd.number,
                            player_name=pairing.player,
                            opponent_name=pairing.opponent,
                            table_number=pairing.table_number,
                            player_wins=pairing.player_wins,
                            opponent_wins=pairing.opponent_wins,
                        )
                    )
                    saved += 1
                elif (
                    existing.opponent_name != pairing.opponent
                    or existing.table_number != pairing.table_number
                    or existing.player_wins != pairing.player_wins
                    or existing.opponent_wins != pairing.opponent_wins
                ):
                    # счёт обычно появляется при повторном импорте после сыгранного раунда
                    existing.opponent_name = pairing.opponent
                    existing.table_number = pairing.table_number
                    existing.player_wins = pairing.player_wins
                    existing.opponent_wins = pairing.opponent_wins
                    saved += 1
        self.db.commit()
        return saved

    def import_tournament(self, tournament_id: int, data: AetherhubTournamentData) -> ImportResult:
        tournament = self.db.get(models.Tournament, tournament_id)
        if tournament is None:
            raise errors.TournamentNotFound(f"Tournament {tournament_id} not found")
        if tournament.status == models.TournamentStatus.CLOSED:
            # Закрытый турнир: только освежаем паринги/счёт (финальные результаты
            # часто появляются к закрытию). Без перерегистрации участников и без
            # уведомлений (new_round_numbers=[]).
            return self._refresh_pairings_only(tournament_id, data)

        registered = 0
        already_registered = 0
        created: list[str] = []

        place_map: dict[str, int] = {}
        normalized_place_map: dict[str, int] = {}
        for idx, sname in enumerate(data.standings):
            if sname.upper() == "BYE":
                continue
            place = idx + 1
            place_map[sname] = place
            normalized_place_map[self._normalize_import_name(sname)] = place

        for name in data.players:
            if name.upper() == "BYE":
                continue
            place = place_map.get(name) or normalized_place_map.get(self._normalize_import_name(name))
            user = self.find_user_by_name(name)
            was_created = False
            if user is None:
                user, was_created = self._get_or_create_user_by_name(name)
            existing = self._get_participant(tournament_id, user.id)
            if existing is not None:
                already_registered += 1
                existing.final_place = place
            else:
                self.db.add(
                    models.Participant(
                        tournament_id=tournament_id,
                        user_id=user.id,
                        final_place=place,
                    )
                )
                registered += 1
            if was_created:
                created.append(name)

        self.db.commit()

        existing_rounds = self._existing_round_numbers(tournament_id)
        new_round_numbers = sorted(r.number for r in data.rounds if r.pairings and r.number not in existing_rounds)
        pairings_saved = self._save_pairings(tournament_id, data.rounds)

        # Self-heal phantom rounds: drop any stored round beyond the real maximum.
        # Older imports could persist clamped duplicate rounds (see AetherhubService);
        # once the parser reports the true round count, remove the stale leftovers.
        real_rounds = [r.number for r in data.rounds if r.pairings]
        if real_rounds:
            self._delete_rounds_above(tournament_id, max(real_rounds))

        return ImportResult(
            registered=registered,
            already_registered=already_registered,
            pairings_saved=pairings_saved,
            created_names=created,
            new_round_numbers=new_round_numbers,
        )

    def _refresh_pairings_only(self, tournament_id: int, data: AetherhubTournamentData) -> ImportResult:
        """Обновить только паринги/счёт (для закрытого турнира). Без перерегистрации."""
        pairings_saved = self._save_pairings(tournament_id, data.rounds)
        real_rounds = [r.number for r in data.rounds if r.pairings]
        if real_rounds:
            self._delete_rounds_above(tournament_id, max(real_rounds))
        return ImportResult(
            registered=0,
            already_registered=0,
            pairings_saved=pairings_saved,
            created_names=[],
            new_round_numbers=[],
        )

    def _delete_rounds_above(self, tournament_id: int, max_round: int) -> int:
        """Delete stored pairings for rounds greater than ``max_round`` (phantom rounds)."""
        deleted = (
            self.db.query(models.RoundPairing)
            .filter(
                models.RoundPairing.tournament_id == tournament_id,
                models.RoundPairing.round_number > max_round,
            )
            .delete(synchronize_session=False)
        )
        if deleted:
            self.db.commit()
        return deleted

    def _existing_round_numbers(self, tournament_id: int) -> set[int]:
        """Round numbers that already have at least one stored pairing for the tournament."""
        rows = self.db.execute(
            select(models.RoundPairing.round_number)
            .where(models.RoundPairing.tournament_id == tournament_id)
            .distinct()
        ).all()
        return {r[0] for r in rows}

    def get_round_numbers(self, tournament_id: int) -> list[int]:
        """All round numbers that have stored pairings for the tournament, ascending."""
        return sorted(self._existing_round_numbers(tournament_id))

    def has_pairings(self, tournament_id: int) -> bool:
        return (
            self.db.execute(
                select(models.RoundPairing.id).where(models.RoundPairing.tournament_id == tournament_id).limit(1)
            ).scalar_one_or_none()
            is not None
        )

    def is_tournament_complete(self, tournament_id: int) -> bool:
        """True, если турнир сыгран до конца: есть паринги и у всех не-бай матчей проставлен счёт.

        Счёт матчей на AetherHub публикуется только ПОСЛЕ завершения турнира (см.
        AetherhubFinalReimportJob), поэтому «у всех матчей есть счёт» — надёжный признак,
        что турнир закончился и финальные стендинги получены.
        """
        pairings = self.get_pairings(tournament_id)
        if not pairings:
            return False
        for p in pairings:
            if p.opponent_name is not None and (p.player_wins is None or p.opponent_wins is None):
                return False
        return True

    def _player_records(self, tournament_id: int) -> dict[str, dict[str, int]]:
        """player_name → {wins, losses, draws, rounds}. Бай (opponent_name=None) считается победой."""
        records: dict[str, dict[str, int]] = {}
        for p in self.get_pairings(tournament_id):
            rec = records.setdefault(p.player_name, {"wins": 0, "losses": 0, "draws": 0, "rounds": 0})
            rec["rounds"] += 1
            if p.opponent_name is None:
                rec["wins"] += 1  # бай — победа
            elif p.player_wins is None or p.opponent_wins is None:
                continue  # счёт неизвестен (для завершённого турнира не встречается)
            elif p.player_wins > p.opponent_wins:
                rec["wins"] += 1
            elif p.player_wins < p.opponent_wins:
                rec["losses"] += 1
            else:
                rec["draws"] += 1
        return records

    def get_undefeated_players(self, tournament_id: int) -> list[UndefeatedPlayer]:
        """Игроки без поражений (X-0): сыграли все раунды, выиграли все матчи, без поражений/ничьих.

        Сортировка по финальному месту (если известно), затем по имени из парингов.
        """
        records = self._player_records(tournament_id)
        if not records:
            return []
        total_rounds = max(self._existing_round_numbers(tournament_id))

        players: list[UndefeatedPlayer] = []
        for name, rec in records.items():
            undefeated = (
                rec["losses"] == 0
                and rec["draws"] == 0
                and rec["rounds"] == total_rounds
                and rec["wins"] == total_rounds
            )
            if not undefeated:
                continue
            user = self.find_user_by_name(name)
            archetype_name: str | None = None
            final_place: int | None = None
            first_name = last_name = None
            if user is not None:
                first_name, last_name = user.first_name, user.last_name
                participant = self._get_participant(tournament_id, user.id)
                if participant is not None:
                    final_place = participant.final_place
                    if participant.archetype is not None:
                        archetype_name = participant.archetype.name
            players.append(
                UndefeatedPlayer(
                    player_name=name,
                    first_name=first_name,
                    last_name=last_name,
                    archetype_name=archetype_name,
                    final_place=final_place,
                    wins=rec["wins"],
                )
            )

        players.sort(key=lambda u: (u.final_place if u.final_place is not None else 10**9, u.player_name.lower()))
        return players

    def get_player_opponents(self, tournament_id: int, participant_id: int) -> tuple[list[OpponentInfo], str | None]:
        """Return (opponents, error_key).

        error_key is None on success, or one of:
          'no_pairings'     — no pairings imported for tournament
          'not_found'       — participant_id does not exist
          'not_in_pairings' — participant's user not matched in pairing names
        """
        pairings = self.get_pairings(tournament_id)
        if not pairings:
            return [], "no_pairings"

        participant = self.db.get(models.Participant, participant_id)
        if participant is None:
            return [], "not_found"

        all_names = {p.player_name for p in pairings} | {p.opponent_name for p in pairings if p.opponent_name}
        name_to_user: dict[str, models.User | None] = {name: self.find_user_by_name(name) for name in all_names}

        player_pairings: list[models.RoundPairing] = []
        for p in pairings:
            u = name_to_user.get(p.player_name)
            if u and u.id == participant.user_id:
                player_pairings.append(p)

        if not player_pairings:
            return [], "not_in_pairings"

        all_parts = list(
            self.db.execute(select(models.Participant).where(models.Participant.tournament_id == tournament_id))
            .scalars()
            .all()
        )
        user_id_to_participant: dict[int, models.Participant] = {p.user_id: p for p in all_parts}

        result: list[OpponentInfo] = []
        for p in sorted(player_pairings, key=lambda x: x.round_number):
            if p.opponent_name is None:
                result.append(OpponentInfo(p.round_number, None, None, None))
            else:
                opp_user = name_to_user.get(p.opponent_name)
                opp_part = user_id_to_participant.get(opp_user.id) if opp_user else None
                result.append(OpponentInfo(p.round_number, p.opponent_name, opp_user, opp_part))

        return result, None

    def get_pairings(self, tournament_id: int, round_number: int | None = None) -> list[models.RoundPairing]:
        q = select(models.RoundPairing).where(models.RoundPairing.tournament_id == tournament_id)
        if round_number is not None:
            q = q.where(models.RoundPairing.round_number == round_number)
        return list(self.db.execute(q).scalars().all())

    def get_opponent(self, tournament_id: int, player_name: str, round_number: int) -> str | None:
        row = self.db.execute(
            select(models.RoundPairing).where(
                models.RoundPairing.tournament_id == tournament_id,
                models.RoundPairing.round_number == round_number,
                models.RoundPairing.player_name == player_name,
            )
        ).scalar_one_or_none()
        return row.opponent_name if row else None
