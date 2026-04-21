from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session
from sqlalchemy import select

from core import models
from services.aetherhub import AetherhubTournamentData, AetherhubRound
from services.user import UserService


@dataclass
class ImportResult:
    registered: int        # new participants registered (matched or created)
    already_registered: int
    pairings_saved: int
    created_names: list[str]  # players not found in bot — created as placeholders


class AetherhubImportService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._user_svc = UserService(db)

    def _find_user_by_name(self, full_name: str) -> models.User | None:
        """Match 'First Last' or 'Last First' against User.first_name + User.last_name."""
        parts = full_name.strip().split()
        if len(parts) < 2:
            return self.db.execute(
                select(models.User).where(models.User.first_name == full_name)
            ).scalar_one_or_none()

        # Try "First Last" and "Last First" orderings
        for first, last in [(parts[0], " ".join(parts[1:])), (" ".join(parts[:-1]), parts[-1])]:
            user = self.db.execute(
                select(models.User).where(
                    models.User.first_name == first,
                    models.User.last_name == last,
                )
            ).scalar_one_or_none()
            if user:
                return user
        return None

    def _get_or_create_user_by_name(self, full_name: str) -> tuple[models.User, bool]:
        """Find or create a user by full name. Returns (user, was_created)."""
        parts = full_name.strip().split(None, 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else None
        return self._user_svc.get_or_create_by_name(first_name, last_name)

    def _is_registered(self, tournament_id: int, user_id: int) -> bool:
        return self.db.execute(
            select(models.Participant).where(
                models.Participant.tournament_id == tournament_id,
                models.Participant.user_id == user_id,
            )
        ).scalar_one_or_none() is not None

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
                    self.db.add(models.RoundPairing(
                        tournament_id=tournament_id,
                        round_number=rnd.number,
                        player_name=pairing.player,
                        opponent_name=pairing.opponent,
                    ))
                    saved += 1
        self.db.commit()
        return saved

    def import_tournament(
        self, tournament_id: int, data: AetherhubTournamentData
    ) -> ImportResult:
        registered = 0
        already_registered = 0
        created: list[str] = []

        for name in data.players:
            user = self._find_user_by_name(name)
            was_created = False
            if user is None:
                user, was_created = self._get_or_create_user_by_name(name)
            if self._is_registered(tournament_id, user.id):
                already_registered += 1
            else:
                self.db.add(models.Participant(
                    tournament_id=tournament_id,
                    user_id=user.id,
                ))
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

    def get_pairings(
        self, tournament_id: int, round_number: int | None = None
    ) -> list[models.RoundPairing]:
        q = select(models.RoundPairing).where(
            models.RoundPairing.tournament_id == tournament_id
        )
        if round_number is not None:
            q = q.where(models.RoundPairing.round_number == round_number)
        return list(self.db.execute(q).scalars().all())

    def get_opponent(
        self, tournament_id: int, player_name: str, round_number: int
    ) -> str | None:
        row = self.db.execute(
            select(models.RoundPairing).where(
                models.RoundPairing.tournament_id == tournament_id,
                models.RoundPairing.round_number == round_number,
                models.RoundPairing.player_name == player_name,
            )
        ).scalar_one_or_none()
        return row.opponent_name if row else None
