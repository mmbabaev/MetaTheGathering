from __future__ import annotations

import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, TelegramError

from bot.deeplink import deck_deeplink, registration_deeplink
from core import models
from core.config import Club, settings
from core.database import SessionLocal
from services.endstep_table_titles import is_konetskhod_club
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.registration_message import (
    HIDDEN_PARTICIPANT_COUNT,
    RegistrationMessageService,
    format_registration_message,
)

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _markup(button_url: str | None, button_label: str = "📝 Записать колоду"):
    if not button_url:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(button_label, url=button_url)]])


def _konetskhod_icon(tournament: models.Tournament | None) -> Path | None:
    """Иконка «Концехода» для анонса записи; только для регулярного Endstep-ru."""
    if tournament is None or tournament.is_draft or not is_konetskhod_club(tournament.club):
        return None
    raw = settings.KONETSKHOD_ICON_PATH.strip()
    if not raw:
        return None
    path = Path(raw) if Path(raw).is_absolute() else _REPO_ROOT / raw
    return path if path.is_file() else None


async def _send_registration_message(bot, chat_id: int, text: str, markup, icon: Path | None):
    """Photo-with-caption для Концехода (если иконка доступна), иначе обычный текст."""
    if icon is not None:
        with icon.open("rb") as photo:
            return await bot.send_photo(chat_id=chat_id, photo=photo, caption=text, reply_markup=markup)
    return await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)


async def send_registration_open(
    bot, db, club: Club, tournament_id: int, base_text: str, *, owner_chat_id: int | None = None
) -> int:
    if bot is None:
        return 0
    targets = {cid for cid in (club.chat_id, owner_chat_id) if cid}
    if not targets:
        return 0

    tournament = db.get(models.Tournament, tournament_id)
    button_url = None
    try:
        me = await bot.get_me()
        button_url = (
            registration_deeplink(me.username, tournament_id)
            if tournament is not None and tournament.is_draft
            else deck_deeplink(me.username, tournament_id)
        )
    except TelegramError:
        logger.exception("send_registration_open: get_me failed for #%s — шлём без кнопки", tournament_id)

    live_count_enabled = FeatureFlagService(db).is_enabled(FeatureFlags.LIVE_REGISTRATION_COUNT)
    service = RegistrationMessageService(db)
    button_label = "📝 Записаться" if tournament is not None and tournament.is_draft else "📝 Записать колоду"
    participant_count = service.participant_count(tournament_id)
    text = format_registration_message(base_text, participant_count) if live_count_enabled else base_text
    sent = 0
    icon = _konetskhod_icon(tournament)
    for chat_id in targets:
        try:
            message = await _send_registration_message(bot, chat_id, text, _markup(button_url, button_label), icon)
            sent += 1
            if not isinstance(message.message_id, int):
                continue
            service.upsert_last(
                tournament_id=tournament_id,
                chat_id=chat_id,
                message_id=message.message_id,
                base_text=base_text,
                button_url=button_url,
                participant_count=(participant_count if live_count_enabled else HIDDEN_PARTICIPANT_COUNT),
            )
        except TelegramError:
            logger.exception("send_registration_open: send to %s failed for #%s", chat_id, tournament_id)
        except Exception:
            db.rollback()
            logger.exception("send_registration_open: tracking failed for %s in #%s", chat_id, tournament_id)
    return sent


class RegistrationMessageRefreshJob:
    async def run(self, bot, db=None) -> None:
        close_db = db is None
        if close_db:
            db = SessionLocal()
        try:
            live_count_enabled = FeatureFlagService(db).is_enabled(FeatureFlags.LIVE_REGISTRATION_COUNT)
            service = RegistrationMessageService(db)
            rows = service.list_stale_active() if live_count_enabled else service.list_counted_active()
            for row, participant_count in rows:
                rendered_count = participant_count if live_count_enabled else HIDDEN_PARTICIPANT_COUNT
                text = (
                    format_registration_message(row.base_text, participant_count)
                    if live_count_enabled
                    else row.base_text
                )
                try:
                    button_label = "📝 Записаться" if row.tournament.is_draft else "📝 Записать колоду"
                    markup = _markup(row.button_url, button_label)
                    try:
                        await bot.edit_message_text(
                            chat_id=row.chat_id,
                            message_id=row.message_id,
                            text=text,
                            reply_markup=markup,
                        )
                    except BadRequest as exc:
                        if "no text in the message" not in str(exc).lower():
                            raise
                        # Анонс Концехода отправлен фото: текст живёт в caption.
                        await bot.edit_message_caption(
                            chat_id=row.chat_id,
                            message_id=row.message_id,
                            caption=text,
                            reply_markup=markup,
                        )
                except BadRequest as exc:
                    message = str(exc).lower()
                    if "message is not modified" in message:
                        service.mark_rendered(row.id, row.message_id, rendered_count)
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
                    service.mark_rendered(row.id, row.message_id, rendered_count)
        finally:
            if close_db:
                db.close()
