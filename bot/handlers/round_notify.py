"""Pure logic for new-round opponent notifications.

Pipeline (shared by production and debug):

    collect  →  enrich (DataLens)  →  format  →  [deliver]

Only two things differ between production and debug, and they are NOT part of
building the message:
  - WHO receives it (production: opted-in + allow-listed players; debug: only the
    requester), passed in as a recipient filter / source;
  - delivery (the Telegram layer sends to real recipients vs. only the admin).

The message itself — data collection + DataLens enrichment + formatting — goes
through the SAME code for both, so debug previews exactly what production sends.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from bot.messages import format_opponent_notification
from services.round_notifications import RoundNotification, RoundNotificationService
from services.user import UserService


@dataclass
class OutgoingNotification:
    """One DM to deliver: recipient + ready text."""

    tg_id: int
    text: str


class RoundNotifyHandler:
    def __init__(self, notifications: RoundNotificationService, users: UserService) -> None:
        self.notifications = notifications
        self.users = users

    # ── public: production / debug differ only in source + recipient filter ──────

    def build_for_new_rounds(
        self,
        tournament_id: int,
        round_numbers: list[int],
        *,
        is_allowed: Callable[[int], bool] | None = None,
    ) -> list[OutgoingNotification]:
        """Production: opted-in (and allow-listed) recipients paired in the new rounds.

        ``is_allowed`` (notify allow-list, from config) is applied with the opt-in
        gate BEFORE enrichment, so DataLens is never queried for someone who won't
        receive the message.
        """

        def keep(n: RoundNotification) -> bool:
            return (is_allowed is None or is_allowed(n.tg_id)) and self.users.wants_opponent_notifications(n.tg_id)

        return self._build(self.notifications.build_for_rounds(tournament_id, round_numbers), keep)

    def build_for_requester(self, tournament_id: int, to_tg_id: int) -> list[OutgoingNotification]:
        """Debug: only the requester's OWN notifications, across all rounds.

        Bypasses the opt-in gate so an admin previews what they would receive.
        Builds each message through the SAME pipeline as production.
        """
        return self._build(self.notifications.build_for_tournament(tournament_id), lambda n: n.tg_id == to_tg_id)

    # ── shared pipeline ──────────────────────────────────────────────────────────

    def _build(
        self, notifications: Iterable[RoundNotification], keep: Callable[[RoundNotification], bool]
    ) -> list[OutgoingNotification]:
        """collect → (filter) → enrich → format. Used by both production and debug."""
        return [self._render(n) for n in notifications if keep(n)]

    def _render(self, n: RoundNotification) -> OutgoingNotification:
        self.notifications.enrich(n)  # DataLens stats (in-place)
        return OutgoingNotification(tg_id=n.tg_id, text=self._format(n))

    @staticmethod
    def _format(n: RoundNotification) -> str:
        """Готовый объект данных → текст. Чистое форматирование, без сбора данных."""
        return format_opponent_notification(
            round_number=n.round_number,
            table_number=n.table_number,
            opponent_name=n.opponent_name,
            opponent_username=n.opponent_username,
            opponent_decks=n.opponent_decks,
            is_bye=n.is_bye,
            datalens_decks=n.datalens_decks,
            head_to_head=n.head_to_head,
        )
