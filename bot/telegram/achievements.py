"""Telegram-слой ачивок: команда /achievements и доставка отчёта.

Маршрутизация получателя — единственное место, где решается, кому уходят ачивки.
Пока флаг ``achievementsPlayerDm`` выключен, адресат ровно один: владелец
(``settings.OWNER_CHAT_ID``). Именно здесь произойдёт переключение на самих игроков,
и оно требует явного подтверждения владельца — это новый путь массовой рассылки DM
(см. CLAUDE.md «Notification safety» и docs/achievements.md §6).
"""

from __future__ import annotations

import asyncio
import io
import logging

from telegram import InputMediaPhoto, Update
from telegram.ext import ContextTypes

from bot.features import FeatureService
from bot.handlers.achievements import AchievementsHandler, format_shelf
from bot.handlers.base import HandlerResult
from core import models
from core.config import settings
from core.database import SessionLocal
from services.achievement_delivery import (
    STATUS_SENT,
    create_owner_deliveries,
    pending_owner_deliveries,
)
from services.achievement_image import render_achievement_card, render_shelf
from services.achievement_report_log import write_achievement_report_log
from services.achievements import AchievementService, build_report
from services.feature_flags import FeatureFlagService
from services.user import UserService

logger = logging.getLogger(__name__)

# Лимиты Telegram — те же, что у отбивки «сбор завершён» (bot/scheduler.py).
_TG_CAPTION_LIMIT = 1024
_TG_ALBUM_LIMIT = 10


def _handler(db) -> AchievementsHandler:
    return AchievementsHandler(
        AchievementService(db),
        UserService(db),
        FeatureService(FeatureFlagService(db)),
    )


async def cmd_achievements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    query = " ".join(context.args).strip() if context.args else None
    db = SessionLocal()
    try:
        shelf = _handler(db).shelf(tg_id=user.id, query=query)
        if isinstance(shelf, HandlerResult):  # нет прав / игрок не найден
            if not shelf.silent:
                await msg.reply_text(shelf.text)
            return
        text = format_shelf(shelf.title, shelf.views)
        png = await _render_shelf(shelf)
    finally:
        db.close()

    if png is None:  # картинка не обязана получиться — текст важнее
        await msg.reply_text(text)
        return
    caption = text if len(text) <= _TG_CAPTION_LIMIT else None
    await msg.reply_photo(photo=io.BytesIO(png), caption=caption)
    if caption is None:
        await msg.reply_text(text)


async def _render_shelf(shelf) -> bytes | None:
    """Полка картинкой. None — не нарисовалась; рисуем в потоке, это ~100 мс CPU."""
    try:
        return await asyncio.to_thread(render_shelf, shelf.image_items(), title=shelf.title)
    except Exception:  # noqa: BLE001 — картинка украшение, текст уже готов
        logger.exception("[achievements] shelf render failed")
        return None


async def _render_cards(granted: list, subtitle: str) -> list[bytes]:
    """Карточки новых ачивок (не больше альбома). Сбой одной не мешает остальным."""
    cards: list[bytes] = []
    for item in granted[:_TG_ALBUM_LIMIT]:
        try:
            cards.append(
                await asyncio.to_thread(
                    render_achievement_card,
                    item.definition,
                    player=item.player,
                    evidence=item.evidence,
                    subtitle=subtitle,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("[achievements] card render failed for %s", item.definition.code)
    return cards


async def _deliver_pending_owner_reports(bot, db, tournament_id: int) -> tuple[int, bool]:
    """Отправить недоставленные части по порядку; успешно отправленные больше не повторять."""
    sent = 0
    for delivery in pending_owner_deliveries(db, tournament_id):
        if delivery.chat_id is None:
            if not settings.OWNER_CHAT_ID:
                logger.warning("[achievements] OWNER_CHAT_ID is not set — report remains pending")
                return sent, False
            delivery.chat_id = settings.OWNER_CHAT_ID

        delivery.attempts += 1
        try:
            await bot.send_message(chat_id=delivery.chat_id, text=delivery.payload)
        except Exception as exc:  # noqa: BLE001 — pending delivery повторится при следующем запуске
            # Не сохраняем текст исключения: он может содержать неожиданные приватные данные.
            delivery.last_error = type(exc).__name__
            db.commit()
            logger.exception("[achievements] could not send report for #%s; delivery remains pending", tournament_id)
            return sent, False

        delivery.status = STATUS_SENT
        delivery.sent_at = models.utc_now()
        delivery.last_error = None
        db.commit()  # фиксируем каждую часть: следующая попытка не задублирует её
        sent += 1

    return sent, not pending_owner_deliveries(db, tournament_id)


async def send_achievements_report(bot, db, tournament_id: int) -> int:
    """Посчитать ачивки турнира и отправить отчёт. Возвращает число отправленных сообщений.

    Теневой режим: один агрегированный отчёт владельцу про всех игроков сразу.
    Идемпотентно — повторный вызов не найдёт новых выдач и промолчит.
    """
    if bot is None:
        return 0
    features = FeatureService(FeatureFlagService(db))
    if not features.are_achievements_enabled():
        return 0

    service = AchievementService(db)
    existing = pending_owner_deliveries(db, tournament_id)
    if existing:
        sent, complete = await _deliver_pending_owner_reports(bot, db, tournament_id)
        if complete:
            service.mark_notified(service.unnotified_for_tournament(tournament_id))
        return sent

    # Выдачи, progress snapshots и outbox создаются в одной транзакции. Если commit
    # не состоится, не будет ни «выдано, но забыто сообщение», ни пустого outbox.
    result = service.process_tournament(tournament_id, commit=False)
    if result is None:
        return 0

    messages = build_report(result)
    if not messages:
        db.commit()
        logger.info("[achievements] tournament #%s: nothing new", tournament_id)
        return 0

    create_owner_deliveries(db, tournament_id, settings.OWNER_CHAT_ID, messages)
    db.commit()

    if settings.ACHIEVEMENT_LOG_DIR:
        try:
            path = write_achievement_report_log(result, messages, settings.ACHIEVEMENT_LOG_DIR)
            logger.info("[achievements] tournament #%s: report logged to %s", tournament_id, path)
        except Exception:  # noqa: BLE001 — файловый лог не должен блокировать owner-отчёт
            logger.exception("[achievements] could not write report log for #%s", tournament_id)

    if features.are_achievement_dms_enabled():
        # Путь «уведомления игрокам» ещё не реализован (фаза 5). Пока флаг включён по ошибке —
        # не рассылаем ничего, а сообщаем владельцу: молча слать всем игрокам недопустимо.
        logger.warning("[achievements] player DMs are flagged on, but not implemented yet — falling back to owner")

    subtitle = " · ".join(part for part in (result.title, result.club) if part)
    sent, complete = await _deliver_pending_owner_reports(bot, db, tournament_id)
    if not complete:
        return sent

    # Карточки новых ачивок — вдогонку к тексту, альбомом. Best-effort: без них отчёт полный.
    if result.granted:
        cards = await _render_cards(result.granted, subtitle)
        if cards:
            try:
                await bot.send_media_group(
                    chat_id=settings.OWNER_CHAT_ID,
                    media=[InputMediaPhoto(io.BytesIO(c)) for c in cards],
                )
            except Exception:  # noqa: BLE001
                logger.exception("[achievements] could not send cards for #%s", tournament_id)

    if sent:
        service.mark_notified(service.unnotified_for_tournament(tournament_id))
        logger.info(
            "[achievements] tournament #%s: granted=%d progress=%d, report sent in %d message(s)",
            tournament_id,
            len(result.granted),
            len(result.progress_changes),
            sent,
        )
    return sent
