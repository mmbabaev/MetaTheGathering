"""Build one club-chat message when AetherHub publishes new rounds."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from core import models
from services.aetherhub_import_service import AetherhubImportService
from services.round_pairings_view import format_round_pairings
from services.round_results import RoundResultsService
from services.schedule import ScheduleService


@dataclass(frozen=True)
class ClubPairingsMessage:
    chat_id: int
    text: str


class ClubPairingsService:
    def __init__(
        self,
        db: Session,
        import_service: AetherhubImportService | None = None,
        schedule_service: ScheduleService | None = None,
    ) -> None:
        self.db = db
        self._import = import_service or AetherhubImportService(db)
        self._results = RoundResultsService(db)
        self._schedule = schedule_service or ScheduleService(db)

    def build_for_new_rounds(self, tournament_id: int, round_numbers: list[int]) -> ClubPairingsMessage | None:
        tournament = self.db.get(models.Tournament, tournament_id)
        if (
            tournament is None
            or tournament.status == models.TournamentStatus.CLOSED
            or not tournament.chat_id
            or not round_numbers
            or not self._schedule.pairings_publication_enabled(tournament.club)
        ):
            return None

        sections = [self._format_round(tournament, round_number) for round_number in sorted(set(round_numbers))]
        sections = [section for section in sections if section]
        if not sections:
            return None
        return ClubPairingsMessage(chat_id=tournament.chat_id, text="\n\n".join(sections))

    def _format_round(self, tournament: models.Tournament, round_number: int) -> str:
        matches = self._results.list_round(tournament.id, round_number)
        if not matches:
            return ""
        return format_round_pairings(tournament.title, tournament.status.label_ru, round_number, matches)
