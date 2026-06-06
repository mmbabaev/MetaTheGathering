"""Telegram delivery for new-round opponent notifications.

Thin I/O layer: builds notifications via RoundNotificationService (pure logic) and
DMs each recipient. Respects the notify allow-list and swallows per-user send errors.
"""

from __future__ import annotations

import logging

from bot.messages import format_opponent_notification
from core.config import settings
from services.aetherhub_import_service import AetherhubImportService
from services.round_notifications import RoundNotificationService
from services.user import UserService

logger = logging.getLogger(__name__)


def _is_notify_allowed(tg_user_id: int) -> bool:
    allowed = settings.notify_allowed_ids
    return allowed is None or tg_user_id in allowed


async def send_round_notifications(bot, db, tournament_id: int, round_numbers: list[int]) -> int:
    """DM each self-registered player about their opponent in the given new rounds.

    Opt-in per user: only players who enabled "Уведомления об оппоненте" in /settings
    (``notify_opponent_rounds``, OFF by default) receive these notifications.

    Returns the number of messages successfully sent.
    """
    if not round_numbers or bot is None:
        return 0

    user_svc = UserService(db)

    notifications = RoundNotificationService(db).build_for_rounds(tournament_id, round_numbers)
    sent = 0
    for n in notifications:
        if not _is_notify_allowed(n.tg_id):
            continue
        if not user_svc.wants_opponent_notifications(n.tg_id):
            continue  # user has not opted in
        text = format_opponent_notification(
            round_number=n.round_number,
            table_number=n.table_number,
            opponent_name=n.opponent_name,
            opponent_username=n.opponent_username,
            opponent_decks=n.opponent_decks,
            is_bye=n.is_bye,
        )
        try:
            await bot.send_message(chat_id=n.tg_id, text=text)
            sent += 1
        except Exception as e:
            logger.warning("[round_notify] could not DM tg_id=%s: %s", n.tg_id, e)

    if sent:
        logger.info(
            "[round_notify] sent %d notifications for tournament #%s rounds=%s",
            sent,
            tournament_id,
            round_numbers,
        )
    return sent


async def send_debug_round_notifications(bot, db, tournament_id: int, to_tg_id: int) -> int:
    """Debug helper: DM the requester THEIR OWN round notifications, across all rounds.

    Bypasses the scheduler and the new-round trigger so an admin can preview exactly
    what *they* would receive. Only ever messages `to_tg_id` — never any other player.
    Returns the number of messages successfully sent.
    """
    import_service = AetherhubImportService(db)
    rounds = import_service.get_round_numbers(tournament_id)
    notifications = RoundNotificationService(db, import_service=import_service).build_for_rounds(tournament_id, rounds)

    # Only the requester's own notifications — never broadcast other players' messages.
    own = [n for n in notifications if n.tg_id == to_tg_id]

    sent = 0
    for n in own:
        text = format_opponent_notification(
            round_number=n.round_number,
            table_number=n.table_number,
            opponent_name=n.opponent_name,
            opponent_username=n.opponent_username,
            opponent_decks=n.opponent_decks,
            is_bye=n.is_bye,
        )
        try:
            await bot.send_message(chat_id=to_tg_id, text=text)
            sent += 1
        except Exception as e:
            logger.warning("[round_notify] debug DM to %s failed: %s", to_tg_id, e)

    logger.info(
        "[round_notify] debug: sent %d own notifications (of %d total) for tournament #%s to %s",
        sent,
        len(notifications),
        tournament_id,
        to_tg_id,
    )
    return sent
