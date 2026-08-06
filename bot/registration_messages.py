from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, TelegramError

from bot.deeplink import deck_deeplink
from core.config import Club
from core.database import SessionLocal
from services.registration_message import RegistrationMessageService, format_registration_message

logger = logging.getLogger(__name__)


def _markup(button_url: str | None):
    if not button_url:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton("📝 Записать колоду", url=button_url)]])


async def send_registration_open(
    bot, db, club: Club, tournament_id: int, base_text: str, *, owner_chat_id: int | None = None
) -> None:
    if bot is None:
        return
    targets = {cid for cid in (club.chat_id, owner_chat_id) if cid}
    if not targets:
        return

    button_url = None
    try:
        me = await bot.get_me()
        button_url = deck_deeplink(me.username, tournament_id)
    except TelegramError:
        logger.exception("send_registration_open: get_me failed for #%s — шлём без кнопки", tournament_id)

    service = RegistrationMessageService(db)
    participant_count = service.participant_count(tournament_id)
    text = format_registration_message(base_text, participant_count)
    for chat_id in targets:
        try:
            message = await bot.send_message(chat_id=chat_id, text=text, reply_markup=_markup(button_url))
            if not isinstance(message.message_id, int):
                continue
            service.upsert_last(
                tournament_id=tournament_id,
                chat_id=chat_id,
                message_id=message.message_id,
                base_text=base_text,
                button_url=button_url,
                participant_count=participant_count,
            )
        except TelegramError:
            logger.exception("send_registration_open: send to %s failed for #%s", chat_id, tournament_id)
        except Exception:
            db.rollback()
            logger.exception("send_registration_open: tracking failed for %s in #%s", chat_id, tournament_id)


class RegistrationMessageRefreshJob:
    async def run(self, bot, db=None) -> None:
        close_db = db is None
        if close_db:
            db = SessionLocal()
        try:
            service = RegistrationMessageService(db)
            for row, participant_count in service.list_stale_active():
                text = format_registration_message(row.base_text, participant_count)
                try:
                    await bot.edit_message_text(
                        chat_id=row.chat_id,
                        message_id=row.message_id,
                        text=text,
                        reply_markup=_markup(row.button_url),
                    )
                except BadRequest as exc:
                    message = str(exc).lower()
                    if "message is not modified" in message:
                        service.mark_rendered(row.id, row.message_id, participant_count)
                    elif "message to edit not found" in message or "message can't be edited" in message:
                        service.disable(row.id, row.message_id)
                    else:
                        logger.warning("registration message edit failed for row %s: %s", row.id, exc)
                except Forbidden:
                    service.disable(row.id, row.message_id)
                except TelegramError:
                    logger.warning("temporary registration message edit failure for row %s", row.id, exc_info=True)
                except Exception:
                    logger.exception("registration message refresh failed for row %s", row.id)
                else:
                    service.mark_rendered(row.id, row.message_id, participant_count)
        finally:
            if close_db:
                db.close()
