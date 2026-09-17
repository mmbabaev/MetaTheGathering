"""Targeted delivery of internal-Swiss archetype/decklist reminders."""

from __future__ import annotations

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards import CB_DECKLIST_EDIT, CB_REGISTER
from core.config import settings
from services.swiss_requirements_reminders import SwissRequirementsReminderService

logger = logging.getLogger(__name__)


def _is_notify_allowed(tg_id: int) -> bool:
    allowed = settings.notify_allowed_ids
    return allowed is None or tg_id in allowed


async def send_swiss_requirements_reminders(bot, db, now: datetime) -> int:
    """DM each genuine due participant once; mark only successful deliveries."""
    if bot is None:
        return 0
    service = SwissRequirementsReminderService(db)
    sent: list[int] = []
    for recipient in service.pending(now):
        if not _is_notify_allowed(recipient.tg_id):
            logger.info("[swiss_requirements] skip tg_id=%s (not in allowed list)", recipient.tg_id)
            continue
        missing = []
        rows = []
        if recipient.missing_archetype:
            missing.append("архетип")
            rows.append(
                [
                    InlineKeyboardButton(
                        "🃏 Выбрать архетип",
                        callback_data=f"{CB_REGISTER}:{recipient.tournament_id}",
                    )
                ]
            )
        if recipient.missing_decklist:
            missing.append("деклист")
            if not recipient.missing_archetype:
                rows.append(
                    [
                        InlineKeyboardButton(
                            "📄 Загрузить деклист",
                            callback_data=f"{CB_DECKLIST_EDIT}:{recipient.tournament_id}",
                        )
                    ]
                )
        text = (
            "⏰ До начала Swiss-турнира осталось 15 минут. "
            f"У тебя не заполнен{'ы' if len(missing) > 1 else ''}: {', '.join(missing)}."
        )
        try:
            await bot.send_message(
                chat_id=recipient.tg_id,
                text=text,
                reply_markup=InlineKeyboardMarkup(rows),
            )
            sent.append(recipient.participant_id)
        except Exception as exc:  # noqa: BLE001 - one unavailable DM must not stop others
            logger.warning(
                "[swiss_requirements] could not DM tg_id=%s for tournament #%s: %s",
                recipient.tg_id,
                recipient.tournament_id,
                exc,
            )
    service.mark_sent(sent)
    return len(sent)
