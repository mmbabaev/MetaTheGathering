"""Safe owner-only actions available in the debug bot."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.meta_police_message import send_debug_meta_police_preview
from core.config import settings
from core.database import SessionLocal

logger = logging.getLogger(__name__)


async def callback_debug_meta_police(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send an interactive meta-police preview exclusively to the owner who pressed the button."""
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    if not settings.DEBUG or user.id != settings.OWNER_CHAT_ID:
        await query.answer("Кнопка доступна только владельцу в debug-боте.", show_alert=True)
        return
    try:
        tournament_id = int(query.data.split(":", 1)[1])
    except (AttributeError, IndexError, TypeError, ValueError):
        await query.answer("Ошибка данных.", show_alert=True)
        return

    db = SessionLocal()
    try:
        count = await send_debug_meta_police_preview(
            context.bot,
            db,
            tournament_id,
            requester_tg_id=user.id,
        )
    except ValueError as exc:
        await query.answer(str(exc), show_alert=True)
    except Exception:  # noqa: BLE001 — a debug action must not crash the update loop
        logger.exception("debug meta-police preview failed for #%s", tournament_id)
        await query.answer("Не удалось собрать debug-превью.", show_alert=True)
    else:
        await query.answer(f"Отправил live-превью: {count} игроков без колоды.", show_alert=True)
    finally:
        db.close()
