"""Best-effort updates of the already-sent meta-police group message."""

from __future__ import annotations

import asyncio
import logging
from weakref import WeakKeyDictionary

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, TelegramError

from bot.deeplink import fill_missing_deeplink
from bot.messages import format_missing_decks_reminder
from core import models
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.meta_police_message import MetaPoliceMessageService
from services.tournament import TournamentService

logger = logging.getLogger(__name__)
_refresh_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[int, asyncio.Lock]] = WeakKeyDictionary()


def _markup(button_url: str | None):
    if not button_url:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton("Записать", url=button_url)]])


async def send_debug_meta_police_preview(bot, db, tournament_id: int, requester_tg_id: int) -> int:
    """Send a live preview only to the owner who triggered the debug action."""
    tournament = db.get(models.Tournament, tournament_id)
    if tournament is None:
        raise ValueError("Турнир не найден.")
    if tournament.status == models.TournamentStatus.CLOSED:
        raise ValueError("Для теста нужен незакрытый турнир.")
    if not FeatureFlagService(db).is_enabled(FeatureFlags.RECORD_OPPONENTS):
        raise ValueError("Сначала включите feature flag recordOpponents.")

    participants = TournamentService(db).list_participants_for_tournament(tournament_id)
    missing = [participant for participant in participants if participant.archetype_id is None]
    if not missing:
        raise ValueError("В турнире нет игроков без колоды.")

    me = await bot.get_me()
    bot_username = getattr(me, "username", None)
    if not bot_username:
        raise ValueError("Не удалось определить username debug-бота.")
    button_url = fill_missing_deeplink(bot_username, tournament.id)
    message = await bot.send_message(
        chat_id=requester_tg_id,
        text=format_missing_decks_reminder(
            tournament.title,
            missing,
            community_fill_enabled=True,
        ),
        reply_markup=_markup(button_url),
        parse_mode="HTML",
    )
    message_id = getattr(message, "message_id", None)
    if not isinstance(message_id, int):
        raise RuntimeError("Telegram не вернул message_id для debug-превью.")

    # Prevent the debug scheduler from later posting the same reminder to a real club chat.
    tournament.missing_decks_reminder_1d_sent_at = tournament.missing_decks_reminder_1d_sent_at or models.utc_now()
    MetaPoliceMessageService(db).upsert(
        tournament_id=tournament.id,
        chat_id=requester_tg_id,
        message_id=message_id,
        participant_ids=[participant.id for participant in missing],
        button_url=button_url,
    )
    return len(missing)


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
