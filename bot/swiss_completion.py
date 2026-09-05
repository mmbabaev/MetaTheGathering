"""Public completion announcement for an internal Swiss tournament."""

from __future__ import annotations

import io
import logging

from telegram import InputMediaPhoto

from bot.chart import build_chart, build_standings
from bot.messages import format_swiss_standings
from core import models
from services.internal_swiss import InternalSwissService

logger = logging.getLogger(__name__)

TEXT_PAGE_SIZE = 20
MEDIA_GROUP_LIMIT = 10


async def publish_swiss_completion(bot, db, tournament_id: int) -> bool:
    """Send final text standings and meta images to exactly the tournament chat.

    Tournament closure is already committed by the handler. Delivery is therefore
    best-effort and must never turn a successfully finished tournament back into an
    error screen for the administrator.
    """

    try:
        tournament = db.get(models.Tournament, tournament_id)
        if bot is None or tournament is None or not tournament.chat_id:
            return False
        if tournament.engine_mode != models.TournamentEngineMode.INTERNAL_SWISS:
            return False
        standings = InternalSwissService(db).standings(tournament_id)
        chat_id = tournament.chat_id
        title = tournament.title
        planned_rounds = tournament.swiss_rounds or 0
    except Exception:  # noqa: BLE001 — закрытие уже зафиксировано, публикация best-effort
        logger.exception("publish_swiss_completion: data collection failed for #%s", tournament_id)
        db.rollback()
        return False
    page_count = max(1, (len(standings) + TEXT_PAGE_SIZE - 1) // TEXT_PAGE_SIZE)
    try:
        for page in range(page_count):
            await bot.send_message(
                chat_id=chat_id,
                text=format_swiss_standings(
                    title,
                    planned_rounds,
                    planned_rounds,
                    standings,
                    provisional=False,
                    page=page,
                    page_size=TEXT_PAGE_SIZE,
                ),
                parse_mode="HTML",
            )
    except Exception:  # noqa: BLE001 — закрытие уже зафиксировано, Telegram можно только залогировать
        logger.exception("publish_swiss_completion: text delivery failed for #%s", tournament_id)
        return False

    chart = await build_chart(db, tournament_id)
    standings_images = await build_standings(db, tournament_id)
    images = ([chart] if chart else []) + list(standings_images)
    try:
        for start in range(0, len(images), MEDIA_GROUP_LIMIT):
            group = images[start : start + MEDIA_GROUP_LIMIT]
            if len(group) == 1:
                await bot.send_photo(chat_id=chat_id, photo=io.BytesIO(group[0].png))
            elif group:
                await bot.send_media_group(
                    chat_id=chat_id,
                    media=[InputMediaPhoto(io.BytesIO(image.png)) for image in group],
                )
    except Exception:  # noqa: BLE001 — картинки best-effort, текст уже доставлен
        logger.exception("publish_swiss_completion: image delivery failed for #%s", tournament_id)
    return True
