from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from services.aetherhub import AetherhubRound, AetherhubTournamentData
from services.user import UserService


@dataclass
class ImportResult:
    registered: int  # new participants registered (matched or created)
    already_registered: int
    pairings_saved: int
    created_names: list[str]  # players not found in bot — created as placeholders


class AetherhubImportService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._user_svc = UserService(db)

    def find_user_by_name(self, full_name: str) -> models.User | None:
        """Match full_name against User records using flexible name matching
        (both orderings, case-insensitive, ё/е normalization)."""
        if not full_name.strip():
            return None
        return self._user_svc.find_by_name(full_name)

    def get_unfilled_opponents(self, tournament_id: int, user_id: int, participants: list) -> tuple[list, str | None]:
        """Return (unfilled_opponent_participants, error_key).

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

        opponent_names: set[str] = set()
        for p in pairings:
            u = name_to_user.get(p.player_name)
            if u and u.id == user_id and p.opponent_name:
                opponent_names.add(p.opponent_name)

        if not opponent_names:
            return [], "not_in_pairings"

        opponent_user_ids: set[int] = set()
        for opp_name in opponent_names:
            u = name_to_user.get(opp_name)
            if u:
                opponent_user_ids.add(u.id)

        result = [p for p in participants if p.archetype is None and p.user_id in opponent_user_ids]
        return result, (None if result else "all_filled")

    def _get_or_create_user_by_name(self, full_name: str) -> tuple[models.User, bool]:
        """Find or create a user by full name. Returns (user, was_created)."""
        parts = full_name.strip().split(None, 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else None
        return self._user_svc.get_or_create_by_name(first_name, last_name)

    def _is_registered(self, tournament_id: int, user_id: int) -> bool:
        return (
            self.db.execute(
                select(models.Participant).where(
                    models.Participant.tournament_id == tournament_id,
                    models.Participant.user_id == user_id,
                )
            ).scalar_one_or_none()
            is not None
        )

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
                        )
                    )
                    saved += 1
        self.db.commit()
        return saved

    def import_tournament(self, tournament_id: int, data: AetherhubTournamentData) -> ImportResult:
        registered = 0
        already_registered = 0
        created: list[str] = []

        for name in data.players:
            user = self.find_user_by_name(name)
            was_created = False
            if user is None:
                user, was_created = self._get_or_create_user_by_name(name)
            if self._is_registered(tournament_id, user.id):
                already_registered += 1
            else:
                self.db.add(
                    models.Participant(
                        tournament_id=tournament_id,
                        user_id=user.id,
                    )
                )
                registered += 1
            if was_created:
                created.append(name)

        self.db.commit()
        pairings_saved = self._save_pairings(tournament_id, data.rounds)

        return ImportResult(
            registered=registered,
            already_registered=already_registered,
            pairings_saved=pairings_saved,
            created_names=created,
        )

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
