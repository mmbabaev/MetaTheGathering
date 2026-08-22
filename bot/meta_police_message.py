"""Best-effort updates of the already-sent meta-police group message."""

from __future__ import annotations

import asyncio
import logging
from weakref import WeakKeyDictionary

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, TelegramError

from bot.messages import format_missing_decks_reminder
from services.meta_police_message import MetaPoliceMessageService

logger = logging.getLogger(__name__)
_refresh_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[int, asyncio.Lock]] = WeakKeyDictionary()


def _markup(button_url: str | None):
    if not button_url:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton("Записать", url=button_url)]])


async def refresh_meta_police_message(bot, db, tournament_id: int | None) -> bool:
    """Strike completed rows and remove the button once every tracked deck is filled."""
    if bot is None or tournament_id is None:
        return False
    locks = _refresh_locks.setdefault(asyncio.get_running_loop(), {})
    lock = locks.setdefault(tournament_id, asyncio.Lock())
    async with lock:
        return await _refresh_meta_police_message(bot, db, tournament_id)


async def _refresh_meta_police_message(bot, db, tournament_id: int) -> bool:
    service = MetaPoliceMessageService(db)
    row = service.get_active(tournament_id)
    if row is None:
        return False
    participants = service.tracked_participants(row)
    if not participants:
        return False
    all_filled = all(participant.archetype_id is not None for participant in participants)
    text = format_missing_decks_reminder(
        row.tournament.title,
        participants,
        community_fill_enabled=True,
    )
    try:
        await bot.edit_message_text(
            chat_id=row.chat_id,
            message_id=row.message_id,
            text=text,
            reply_markup=None if all_filled else _markup(row.button_url),
            parse_mode="HTML",
        )
    except BadRequest as exc:
        error = str(exc).lower()
        if "message is not modified" in error:
            return True
        if "message to edit not found" in error or "message can't be edited" in error:
            service.disable(row.id, row.message_id)
        else:
            logger.warning("meta-police message edit failed for tournament #%s: %s", tournament_id, exc)
        return False
    except Forbidden:
        service.disable(row.id, row.message_id)
        return False
    except TelegramError:
        logger.warning("temporary meta-police message edit failure for tournament #%s", tournament_id, exc_info=True)
        return False
    except Exception:
        logger.exception("meta-police message refresh failed for tournament #%s", tournament_id)
        return False
    return True
