"""Build one club-chat message when AetherHub publishes new rounds."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from core import models
from services.aetherhub_import_service import AetherhubImportService
from services.endstep_table_titles import format_endstep_table_title, is_endstep_swiss
from services.round_pairings_view import format_round_pairings
from services.round_results import RoundResultsService
from services.schedule import ScheduleService


@dataclass(frozen=True)
class ClubPairingTableCopy:
    table_number: int
    text: str


@dataclass(frozen=True)
class ClubPairingsMessage:
    chat_id: int
    round_number: int
    text: str
    table_copies: tuple[ClubPairingTableCopy, ...] = ()


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
        messages = [self.build_for_round(tournament_id, number) for number in sorted(set(round_numbers))]
        messages = [message for message in messages if message is not None]
        if not messages:
            return None
        return ClubPairingsMessage(
            chat_id=messages[0].chat_id,
            round_number=messages[-1].round_number,
            text="\n\n".join(message.text for message in messages),
            table_copies=tuple(copy for message in messages for copy in message.table_copies),
        )

    def build_for_round(self, tournament_id: int, round_number: int) -> ClubPairingsMessage | None:
        tournament = self.db.get(models.Tournament, tournament_id)
        if (
            tournament is None
            or tournament.status == models.TournamentStatus.CLOSED
            or not tournament.chat_id
            or not self._schedule.pairings_publication_enabled(tournament.club)
        ):
            return None

        matches = self._results.list_round(tournament.id, round_number)
        if not matches:
            return None
        table_copies = ()
        if is_endstep_swiss(tournament):
            table_copies = tuple(
                ClubPairingTableCopy(
                    table_number=match.table_number if match.table_number is not None else index,
                    text=format_endstep_table_title(match),
                )
                for index, match in enumerate(matches, start=1)
                if match.player2_name is not None
            )
        return ClubPairingsMessage(
            chat_id=tournament.chat_id,
            round_number=round_number,
            text=format_round_pairings(tournament.title, tournament.status.label_ru, round_number, matches),
            table_copies=table_copies,
        )
