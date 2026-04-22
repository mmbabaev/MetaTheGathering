from typing import Iterable

from sqlalchemy.orm import Session

from core import models
from services.errors import TournamentInvalidState, TournamentNotFound


def get_tournament(db: Session, tournament_id: int) -> models.Tournament:
    tournament = db.get(models.Tournament, tournament_id)
    if not tournament:
        raise TournamentNotFound(f"Tournament {tournament_id} not found")
    return tournament


def ensure_tournament_status(
    tournament: models.Tournament,
    allowed: Iterable[models.TournamentStatus],
) -> None:
    if tournament.status not in allowed:
        allowed_str = ", ".join(s.value for s in allowed)
        raise TournamentInvalidState(
            f"Tournament #{tournament.id} is in status {tournament.status.value}, expected one of: {allowed_str}"
        )
