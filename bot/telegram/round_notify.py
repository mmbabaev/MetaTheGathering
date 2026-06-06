"""Telegram delivery for new-round opponent notifications.

Thin I/O layer: builds messages via RoundNotifyHandler (pure logic), applies the
notify allow-list, and DMs each recipient. Per-user send errors are swallowed.
"""

from __future__ import annotations

import logging

from bot.handlers.round_notify import OutgoingNotification, RoundNotifyHandler
from core.config import settings
from services.datalens import DataLensService
from services.round_notifications import RoundNotificationService
from services.user import UserService

logger = logging.getLogger(__name__)


def _is_notify_allowed(tg_user_id: int) -> bool:
    allowed = settings.notify_allowed_ids
    return allowed is None or tg_user_id in allowed


def _handler(db, datalens_service: DataLensService | None = None) -> RoundNotifyHandler:
    return RoundNotifyHandler(
        RoundNotificationService(db, datalens_service=datalens_service),
        UserService(db),
    )


async def _deliver(bot, messages: list[OutgoingNotification]) -> int:
    sent = 0
    for m in messages:
        try:
            await bot.send_message(chat_id=m.tg_id, text=m.text)
            sent += 1
        except Exception as e:  # noqa: BLE001 — один сбойный DM не должен ронять рассылку
            logger.warning("[round_notify] could not DM tg_id=%s: %s", m.tg_id, e)
    return sent


async def send_round_notifications(
    bot, db, tournament_id: int, round_numbers: list[int], *, datalens_service: DataLensService | None = None
) -> int:
    """DM each self-registered, opted-in player about their opponent in the new rounds.

    Opt-in per user: only players who enabled "Уведомления об оппоненте" in /settings
    (``notify_opponent_rounds``, OFF by default) receive these notifications.
    ``datalens_service`` (optional) enriches the message with opponent stats.

    Returns the number of messages successfully sent.
    """
    if not round_numbers or bot is None:
        return 0

    messages = _handler(db, datalens_service).build_for_new_rounds(
        tournament_id, round_numbers, is_allowed=_is_notify_allowed
    )
    sent = await _deliver(bot, messages)
    if sent:
        logger.info(
            "[round_notify] sent %d notifications for tournament #%s rounds=%s",
            sent,
            tournament_id,
            round_numbers,
        )
    return sent


async def send_debug_round_notifications(
    bot, db, tournament_id: int, to_tg_id: int, *, datalens_service: DataLensService | None = None
) -> int:
    """Debug helper: DM the requester THEIR OWN round notifications, across all rounds.

    Bypasses the scheduler/opt-in so an admin can preview exactly what *they* would
    receive. Only ever messages `to_tg_id` — never any other player.
    Returns the number of messages successfully sent.
    """
    messages = _handler(db, datalens_service).build_for_requester(tournament_id, to_tg_id)
    sent = await _deliver(bot, messages)
    logger.info(
        "[round_notify] debug: sent %d own notifications for tournament #%s to %s",
        sent,
        tournament_id,
        to_tg_id,
    )
    return sent
