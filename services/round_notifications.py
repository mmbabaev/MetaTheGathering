"""Build per-player notifications about their opponent when a new round appears.

Pure business logic: produces a list of RoundNotification dataclasses. The Telegram
layer is responsible for actually delivering the messages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from services.aetherhub_import_service import AetherhubImportService
from services.archetype import ArchetypeService
from services.datalens import DataLensService, StatRow

logger = logging.getLogger(__name__)

OPPONENT_DECKS_LIMIT = 3
DATALENS_DECKS_LIMIT = 3  # колод соперника из DataLens в сообщении (сортировка по матчам)


@dataclass
class RoundNotification:
    tg_id: int  # recipient (always a real Telegram account, tg_id > 0)
    round_number: int
    table_number: int | None
    opponent_name: str | None  # None when it's a bye
    opponent_username: str | None
    opponent_decks: list[str] = field(default_factory=list)  # opponent's recent tournament decks
    is_bye: bool = False
    recipient_name: str = ""  # intended recipient's display name (for debug/logging)


class RoundNotificationService:
    def __init__(
        self,
        db: Session,
        import_service: AetherhubImportService | None = None,
        archetype_service: ArchetypeService | None = None,
        datalens_service: DataLensService | None = None,
    ) -> None:
        self.db = db
        self._import = import_service or AetherhubImportService(db)
        self._archetypes = archetype_service or ArchetypeService(db)
        # None → обогащение из DataLens отключено (например, в юнит-тестах).
        self._datalens = datalens_service

    def build_for_rounds(self, tournament_id: int, round_numbers: list[int]) -> list[RoundNotification]:
        """Build notifications for every given round, flattened into one list."""
        result: list[RoundNotification] = []
        for round_number in round_numbers:
            result.extend(self.build_for_round(tournament_id, round_number))
        return result

    def build_for_tournament(self, tournament_id: int) -> list[RoundNotification]:
        """Build notifications across all known rounds of the tournament."""
        return self.build_for_rounds(tournament_id, self._import.get_round_numbers(tournament_id))

    def build_for_round(self, tournament_id: int, round_number: int) -> list[RoundNotification]:
        """One notification per self-registered, real-Telegram player paired in this round."""
        pairings = self._import.get_pairings(tournament_id, round_number)
        if not pairings:
            return []

        names = {p.player_name for p in pairings} | {p.opponent_name for p in pairings if p.opponent_name}
        name_to_user = {name: self._import.find_user_by_name(name) for name in names}
        participants = self._participants_by_user_id(tournament_id)

        notifications: list[RoundNotification] = []
        for pairing in pairings:
            recipient = name_to_user.get(pairing.player_name)
            if not self._is_notifiable(recipient, participants):
                continue
            notifications.append(
                self._build_notification(tournament_id, round_number, pairing, recipient, name_to_user)
            )
        return notifications

    def _is_notifiable(self, recipient: models.User | None, participants: dict[int, models.Participant]) -> bool:
        """Notify only players who registered themselves and have a real Telegram account."""
        if recipient is None or recipient.tg_id <= 0:
            return False
        participant = participants.get(recipient.id)
        return participant is not None and not participant.added_by_admin

    def _build_notification(
        self,
        tournament_id: int,
        round_number: int,
        pairing: models.RoundPairing,
        recipient: models.User,
        name_to_user: dict[str, models.User | None],
    ) -> RoundNotification:
        recipient_name = self._display_name(recipient)
        if pairing.opponent_name is None:
            return RoundNotification(
                tg_id=recipient.tg_id,
                round_number=round_number,
                table_number=pairing.table_number,
                opponent_name=None,
                opponent_username=None,
                is_bye=True,
                recipient_name=recipient_name,
            )

        opponent = name_to_user.get(pairing.opponent_name)
        decks: list[str] = []
        opponent_username: str | None = None
        if opponent is not None:
            opponent_username = opponent.username
            decks = [
                a.name
                for a in self._archetypes.list_user_tournament_archetypes(
                    opponent.id, exclude_tournament_id=tournament_id, limit=OPPONENT_DECKS_LIMIT
                )
            ]
        return RoundNotification(
            tg_id=recipient.tg_id,
            round_number=round_number,
            table_number=pairing.table_number,
            opponent_name=pairing.opponent_name,
            opponent_username=opponent_username,
            opponent_decks=decks,
            recipient_name=recipient_name,
        )

    def scout(self, recipient_name: str, opponent_name: str | None) -> tuple[list[StatRow], StatRow | None]:
        """Обогащение сообщения статистикой соперника из DataLens.

        Возвращает ``(колоды соперника за период, личные встречи)``. Делается
        best-effort: если DataLens не инжектирован, это бай, или сеть недоступна —
        возвращаем пустые данные, не роняя рассылку. Вызывать только для тех, кто
        реально получит уведомление (после фильтра opt-in), чтобы не дёргать API зря.
        """
        if self._datalens is None or not opponent_name:
            return [], None
        try:
            scouting = self._datalens.scout_opponent(recipient_name, opponent_name)
            return scouting.opponent_decks[:DATALENS_DECKS_LIMIT], scouting.head_to_head
        except Exception as e:  # noqa: BLE001 — обогащение не должно ронять рассылку
            logger.warning("[round_notify] datalens scout failed for %r vs %r: %s", recipient_name, opponent_name, e)
            return [], None

    @staticmethod
    def _display_name(user: models.User) -> str:
        full = " ".join(p for p in (user.last_name, user.first_name) if p).strip()
        return full or user.display_name or user.username or f"id{user.tg_id}"

    def _participants_by_user_id(self, tournament_id: int) -> dict[int, models.Participant]:
        rows = (
            self.db.execute(select(models.Participant).where(models.Participant.tournament_id == tournament_id))
            .scalars()
            .all()
        )
        return {p.user_id: p for p in rows}
