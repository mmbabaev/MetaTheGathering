"""Безопасные owner-only команды для debug-бота."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.scheduler import send_debug_meta_police_preview
from core.config import settings
from core.database import SessionLocal

logger = logging.getLogger(__name__)


async def cmd_debug_meta_police(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать интерактивное сообщение мета-полиции только вызвавшему владельцу."""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None:
        return
    if not settings.DEBUG or user.id != settings.OWNER_CHAT_ID:
        await message.reply_text("Команда доступна только владельцу в debug-боте.")
        return
    if len(context.args or []) != 1:
        await message.reply_text("Формат: /debug_meta_police <ID турнира>")
        return
    try:
        tournament_id = int(context.args[0])
    except (TypeError, ValueError):
        await message.reply_text("ID турнира должен быть целым числом.")
        return

    db = SessionLocal()
    try:
        await send_debug_meta_police_preview(context.bot, db, tournament_id, requester_chat_id=chat.id)
    except ValueError as exc:
        await message.reply_text(str(exc))
    except Exception:  # noqa: BLE001 — debug-команда не должна падать наружу
        logger.exception("debug meta-police preview failed for #%s", tournament_id)
        await message.reply_text("Не удалось собрать debug-превью.")
    finally:
        db.close()
