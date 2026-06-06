"""Pure logic for new-round opponent notifications.

Decides WHO gets WHICH message (opt-in gate + DataLens enrichment + formatting) and
returns a list of ready-to-send messages. The Telegram layer (`bot/telegram/`) is
responsible for the actual `bot.send_message` fan-out and the allow-list gate.

Dependencies are constructor-injected (like the other handler classes); nothing is
created inside methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

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

    def build_for_new_rounds(
        self,
        tournament_id: int,
        round_numbers: list[int],
        *,
        is_allowed: Callable[[int], bool] | None = None,
    ) -> list[OutgoingNotification]:
        """Messages for each opted-in (and allowed) recipient paired in the new rounds.

        ``is_allowed`` is the notify allow-list predicate, supplied by the Telegram
        layer (reads config). Applied BEFORE DataLens enrichment so we never query
        the API for someone who won't receive the message.
        """
        messages: list[OutgoingNotification] = []
        for n in self.notifications.build_for_rounds(tournament_id, round_numbers):
            if is_allowed is not None and not is_allowed(n.tg_id):
                continue
            if not self.users.wants_opponent_notifications(n.tg_id):
                continue  # user has not opted in
            messages.append(self._render(n))
        return messages

    def build_for_requester(self, tournament_id: int, to_tg_id: int) -> list[OutgoingNotification]:
        """Debug: only the requester's OWN notifications, across all rounds.

        Bypasses the opt-in gate so an admin can preview what they would receive.
        Never includes any other player's messages.
        """
        return [self._render(n) for n in self.notifications.build_for_tournament(tournament_id) if n.tg_id == to_tg_id]

    def _render(self, n: RoundNotification) -> OutgoingNotification:
        datalens_decks, head_to_head = self.notifications.scout(n.recipient_name, n.opponent_name)
        text = format_opponent_notification(
            round_number=n.round_number,
            table_number=n.table_number,
            opponent_name=n.opponent_name,
            opponent_username=n.opponent_username,
            opponent_decks=n.opponent_decks,
            is_bye=n.is_bye,
            datalens_decks=datalens_decks,
            head_to_head=head_to_head,
        )
        return OutgoingNotification(tg_id=n.tg_id, text=text)
