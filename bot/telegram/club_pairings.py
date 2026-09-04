"""Delivery of newly published pairings to the tournament club chat."""

from __future__ import annotations

import logging

from telegram.error import BadRequest, Forbidden, TelegramError

from services.club_pairings import ClubPairingsService
from services.round_pairings_message import RoundPairingsMessageService

logger = logging.getLogger(__name__)


async def send_club_pairings(bot, db, tournament_id: int, round_numbers: list[int]) -> bool:
    if bot is None:
        return False
    builder = ClubPairingsService(db)
    tracker = RoundPairingsMessageService(db)
    sent = False
    for round_number in sorted(set(round_numbers)):
        message = builder.build_for_round(tournament_id, round_number)
        if message is None:
            continue
        try:
            delivered = await bot.send_message(chat_id=message.chat_id, text=message.text, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001 — ошибка чата не должна ронять импорт
            logger.warning(
                "[club_pairings] could not post tournament #%s round=%s: %s", tournament_id, round_number, exc
            )
            continue
        sent = True
        message_id = getattr(delivered, "message_id", None)
        if isinstance(message_id, int):
            try:
                tracker.upsert(tournament_id, round_number, message.chat_id, message_id)
            except Exception:  # noqa: BLE001 — опубликованное сообщение уже нельзя отменить
                db.rollback()
                logger.exception(
                    "[club_pairings] could not track tournament #%s round=%s message", tournament_id, round_number
                )
    if sent:
        logger.info("[club_pairings] posted tournament #%s rounds=%s", tournament_id, round_numbers)
    return sent


async def refresh_club_pairings(bot, db, tournament_id: int, round_number: int) -> bool:
    """Best-effort refresh of the already published card after a score change."""
    if bot is None:
        return False
    try:
        tracker = RoundPairingsMessageService(db)
        tracked = tracker.get_active(tournament_id, round_number)
        if tracked is None:
            return False
        message = ClubPairingsService(db).build_for_round(tournament_id, round_number)
    except Exception:  # noqa: BLE001 — result persistence must survive refresh preparation failures
        db.rollback()
        logger.exception("[club_pairings] could not prepare refresh for tournament #%s", tournament_id)
        return False
    if message is None:
        return False
    try:
        await bot.edit_message_text(
            chat_id=tracked.chat_id,
            message_id=tracked.message_id,
            text=message.text,
            parse_mode="HTML",
        )
    except BadRequest as exc:
        error = str(exc).lower()
        if "message is not modified" in error:
            return True
        if "message to edit not found" in error or "message can't be edited" in error:
            _disable_tracking(tracker, db, tracked.id, tracked.message_id)
        else:
            logger.warning("[club_pairings] could not refresh tracked message #%s: %s", tracked.id, exc)
        return False
    except Forbidden:
        _disable_tracking(tracker, db, tracked.id, tracked.message_id)
        return False
    except TelegramError:
        logger.warning("[club_pairings] temporary refresh failure for tracked message #%s", tracked.id, exc_info=True)
        return False
    except Exception:  # noqa: BLE001 — result persistence must survive a failed public edit
        logger.exception("[club_pairings] refresh failed for tracked message #%s", tracked.id)
        return False
    return True


def _disable_tracking(tracker: RoundPairingsMessageService, db, row_id: int, message_id: int) -> None:
    try:
        tracker.disable(row_id, message_id)
    except Exception:  # noqa: BLE001 — a cleanup failure must not affect result submission
        db.rollback()
        logger.exception("[club_pairings] could not disable tracked message #%s", row_id)
