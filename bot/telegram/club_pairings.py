"""Delivery of newly published pairings to the tournament club chat."""

from __future__ import annotations

import logging

from services.club_pairings import ClubPairingsService

logger = logging.getLogger(__name__)


async def send_club_pairings(bot, db, tournament_id: int, round_numbers: list[int]) -> bool:
    if bot is None:
        return False
    message = ClubPairingsService(db).build_for_new_rounds(tournament_id, round_numbers)
    if message is None:
        return False
    try:
        await bot.send_message(chat_id=message.chat_id, text=message.text, parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001 — ошибка чата не должна ронять импорт
        logger.warning("[club_pairings] could not post tournament #%s: %s", tournament_id, exc)
        return False
    logger.info("[club_pairings] posted tournament #%s rounds=%s", tournament_id, round_numbers)
    return True
