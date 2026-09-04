"""Build one club-chat message when AetherHub publishes new rounds."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from core import models
from services.aetherhub_import_service import AetherhubImportService
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
        self._schedule = schedule_service or ScheduleService(db)

    def build_for_new_rounds(self, tournament_id: int, round_numbers: list[int]) -> ClubPairingsMessage | None:
        tournament = self.db.get(models.Tournament, tournament_id)
        if (
            tournament is None
            or tournament.status == models.TournamentStatus.CLOSED
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
        pairings = self._deduplicate(self._import.get_pairings(tournament.id, round_number))
        if not pairings:
            return ""
        lines = [f"📋 {tournament.title} · раунд {round_number}"]
        for pairing in pairings:
            table = str(pairing.table_number) if pairing.table_number is not None else "—"
            player = self._format_player(pairing.player_name, tournament)
            opponent = (
                self._format_player(pairing.opponent_name, tournament) if pairing.opponent_name is not None else "BYE"
            )
            lines.append(f"Стол {table}: {player} — {opponent}")
        return "\n".join(lines)

    def _format_player(self, imported_name: str, tournament: models.Tournament) -> str:
        user = self._import.find_user_by_name(imported_name, tournament.id)
        telegram_name = f"@{user.username}" if user is not None and user.username else None
        if tournament.is_online:
            endstep_name = user.endstep_username if user is not None and user.endstep_username else imported_name
            return f"{telegram_name} (Endstep: {endstep_name})" if telegram_name else f"Endstep: {endstep_name}"
        if telegram_name:
            return telegram_name
        if user is not None:
            full_name = " ".join(part for part in (user.last_name, user.first_name) if part).strip()
            if full_name:
                return full_name
        return imported_name

    @staticmethod
    def _deduplicate(pairings: list[models.RoundPairing]) -> list[models.RoundPairing]:
        """AetherHub stores a normal table in both player directions; show it once."""
        unique: dict[tuple[str, ...], models.RoundPairing] = {}
        for pairing in pairings:
            player = pairing.player_name.strip().casefold()
            if pairing.opponent_name is None:
                key = ("bye", player)
            else:
                opponent = pairing.opponent_name.strip().casefold()
                key = ("pair", *sorted((player, opponent)))
            current = unique.get(key)
            if current is None or (current.table_number is None and pairing.table_number is not None):
                unique[key] = pairing
        return sorted(
            unique.values(),
            key=lambda pairing: (
                pairing.table_number is None,
                pairing.table_number or 0,
                pairing.player_name.casefold(),
            ),
        )
