"""Safe Telegram delivery for players who explicitly chose «Укажу позже»."""

from __future__ import annotations

import logging

from bot.keyboards import fill_deck_keyboard
from core.config import settings
from services.deck_reminders import DeckReminderService, DeckReminderStage

logger = logging.getLogger(__name__)

_MESSAGES = {
    DeckReminderStage.PRESTART: (
        "⏰ Турнир скоро начинается, а ты ещё не указал колоду. Выбери её сейчас:"
    ),
    DeckReminderStage.ROUND2: (
        "🔔 Уже начался второй раунд, а колода всё ещё не указана. Пожалуйста, выбери её:"
    ),
}


def _is_notify_allowed(tg_user_id: int) -> bool:
    allowed = settings.notify_allowed_ids
    return allowed is None or tg_user_id in allowed


async def send_deferred_deck_reminders(bot, db, tournament_id: int, stage: DeckReminderStage) -> int:
    """DM genuine pending recipients once for the requested tournament stage."""
    if bot is None:
        return 0
    service = DeckReminderService(db)
    recipients = service.pending_recipients(tournament_id, stage)
    sent_participant_ids: list[int] = []
    keyboard = fill_deck_keyboard(tournament_id)
    for recipient in recipients:
        if not _is_notify_allowed(recipient.tg_id):
            logger.info(
                "[deck_reminder] skip tg_id=%s (not in allowed list)",
                recipient.tg_id,
            )
            continue
        try:
            await bot.send_message(
                chat_id=recipient.tg_id,
                text=_MESSAGES[stage],
                reply_markup=keyboard,
            )
            sent_participant_ids.append(recipient.participant_id)
        except Exception as exc:  # noqa: BLE001 — one unavailable DM must not stop others
            logger.warning(
                "[deck_reminder] could not DM tg_id=%s for tournament #%s: %s",
                recipient.tg_id,
                tournament_id,
                exc,
            )
    service.mark_sent(sent_participant_ids, stage)
    if sent_participant_ids:
        logger.info(
            "[deck_reminder] sent %s reminders for tournament #%s stage=%s",
            len(sent_participant_ids),
            tournament_id,
            stage.value,
        )
    return len(sent_participant_ids)
