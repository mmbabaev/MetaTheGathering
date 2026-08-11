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

from sqlalchemy import select
from telegram import InputMediaPhoto, Update
from telegram.ext import ContextTypes

from bot.features import FeatureService
from bot.handlers.achievements import AchievementsHandler, format_shelf
from bot.handlers.base import HandlerResult
from core import models
from core.config import settings
from core.database import SessionLocal
from services.achievement_delivery import (
    RECIPIENT_OWNER,
    RECIPIENT_PLAYER,
    STATUS_CANCELLED,
    STATUS_SENT,
    create_owner_deliveries,
    create_player_deliveries,
    pending_deliveries,
)
from services.achievement_image import render_achievement_card, render_shelf
from services.achievement_processing_lease import acquire_achievement_lease, release_achievement_lease
from services.achievement_report_log import write_achievement_report_log
from services.achievements import AchievementService, build_player_report, build_report
from services.feature_flags import FeatureFlagService
from services.user import UserService

logger = logging.getLogger(__name__)

# Лимиты Telegram — те же, что у отбивки «сбор завершён» (bot/scheduler.py).
_TG_CAPTION_LIMIT = 1024
_TG_ALBUM_LIMIT = 10
_PLAYER_DELIVERY_BATCH = 25


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


def _is_notify_allowed(tg_id: int) -> bool:
    allowed = settings.notify_allowed_ids
    return allowed is None or tg_id in allowed


def _player_recipients(db, result) -> dict[int, tuple[int, list[str]]]:
    """Resolve only explicit opt-ins represented in this result."""
    user_ids = {item.user_id for item in result.granted} | {item.user_id for item in result.progress_changes}
    recipients: dict[int, tuple[int, list[str]]] = {}
    for user_id in sorted(user_ids):
        user = db.get(models.User, user_id)
        if user is None or user.tg_id <= 0 or not user.notify_achievements or not _is_notify_allowed(user.tg_id):
            continue
        messages = build_player_report(result, user_id)
        if messages:
            recipients[user_id] = (user.tg_id, messages)
    return recipients


def _player_delivery_allowed(db, delivery) -> bool:
    if delivery.user_id is None or delivery.chat_id is None:
        return False
    user = db.get(models.User, delivery.user_id)
    return bool(user and user.tg_id == delivery.chat_id and user.notify_achievements and _is_notify_allowed(user.tg_id))


async def _deliver_pending_reports(
    bot,
    db,
    tournament_id: int,
    recipient_type: str,
    *,
    limit: int | None = None,
) -> tuple[int, bool]:
    """Retry stable outbox rows; failures are isolated by recipient batch."""
    sent = 0
    failed_reports: set[str] = set()
    for delivery in pending_deliveries(db, tournament_id, recipient_type=recipient_type, limit=limit):
        if delivery.report_id in failed_reports:
            continue
        if recipient_type == RECIPIENT_OWNER and delivery.chat_id is None:
            if not settings.OWNER_CHAT_ID:
                logger.warning("[achievements] OWNER_CHAT_ID is not set — report remains pending")
                break
            delivery.chat_id = settings.OWNER_CHAT_ID
        if recipient_type == RECIPIENT_PLAYER and not _player_delivery_allowed(db, delivery):
            delivery.status = STATUS_CANCELLED
            delivery.last_error = "recipient_not_allowed"
            db.commit()
            continue

        delivery.attempts += 1
        try:
            await bot.send_message(chat_id=delivery.chat_id, text=delivery.payload)
        except Exception as exc:  # noqa: BLE001 — pending delivery повторится при следующем запуске
            # Не сохраняем текст исключения: он может содержать неожиданные приватные данные.
            delivery.last_error = type(exc).__name__
            db.commit()
            failed_reports.add(delivery.report_id)
            logger.exception(
                "[achievements] could not send %s report for #%s; delivery remains pending",
                recipient_type,
                tournament_id,
            )
            continue

        delivery.status = STATUS_SENT
        delivery.sent_at = models.utc_now()
        delivery.last_error = None
        db.commit()  # фиксируем каждую часть: следующая попытка не задублирует её
        sent += 1

    return sent, not pending_deliveries(db, tournament_id, recipient_type=recipient_type)


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

    token = acquire_achievement_lease(db, tournament_id)
    if token is None:
        logger.info("[achievements] tournament #%s is already being processed — skip", tournament_id)
        return 0
    try:
        return await _send_achievements_report_locked(bot, db, tournament_id, features)
    finally:
        release_achievement_lease(db, tournament_id, token)


async def _send_achievements_report_locked(bot, db, tournament_id: int, features: FeatureService) -> int:
    """Расчёт и доставка под межпроцессным DB lease."""

    service = AchievementService(db)
    existing = pending_deliveries(db, tournament_id)
    if existing:
        owner_sent, owner_complete = await _deliver_pending_reports(bot, db, tournament_id, RECIPIENT_OWNER)
        player_sent = 0
        if features.are_achievement_dms_enabled():
            player_sent, _ = await _deliver_pending_reports(
                bot, db, tournament_id, RECIPIENT_PLAYER, limit=_PLAYER_DELIVERY_BATCH
            )
        if owner_complete:
            service.mark_notified(service.unnotified_for_tournament(tournament_id))
        return owner_sent + player_sent

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

    create_owner_deliveries(
        db,
        tournament_id,
        settings.OWNER_CHAT_ID,
        messages,
        processing_run_id=result.processing_run_id,
    )
    if features.are_achievement_dms_enabled() and result.processing_run_id is not None:
        create_player_deliveries(
            db,
            tournament_id,
            _player_recipients(db, result),
            processing_run_id=result.processing_run_id,
        )
    db.commit()

    if settings.ACHIEVEMENT_LOG_DIR:
        try:
            path = write_achievement_report_log(result, messages, settings.ACHIEVEMENT_LOG_DIR)
            logger.info("[achievements] tournament #%s: report logged to %s", tournament_id, path)
        except Exception:  # noqa: BLE001 — файловый лог не должен блокировать owner-отчёт
            logger.exception("[achievements] could not write report log for #%s", tournament_id)

    subtitle = " · ".join(part for part in (result.title, result.club) if part)
    owner_sent, owner_complete = await _deliver_pending_reports(bot, db, tournament_id, RECIPIENT_OWNER)
    player_sent = 0
    if features.are_achievement_dms_enabled():
        player_sent, _ = await _deliver_pending_reports(
            bot, db, tournament_id, RECIPIENT_PLAYER, limit=_PLAYER_DELIVERY_BATCH
        )

    # Карточки новых ачивок — вдогонку к тексту, альбомом. Best-effort: без них отчёт полный.
    if owner_complete and result.granted:
        cards = await _render_cards(result.granted, subtitle)
        if cards:
            try:
                await bot.send_media_group(
                    chat_id=settings.OWNER_CHAT_ID,
                    media=[InputMediaPhoto(io.BytesIO(c)) for c in cards],
                )
            except Exception:  # noqa: BLE001
                logger.exception("[achievements] could not send cards for #%s", tournament_id)

    if owner_complete:
        service.mark_notified(service.unnotified_for_tournament(tournament_id))
    if owner_sent or player_sent:
        logger.info(
            "[achievements] tournament #%s: granted=%d progress=%d, owner=%d player=%d message(s)",
            tournament_id,
            len(result.granted),
            len(result.progress_changes),
            owner_sent,
            player_sent,
        )
    return owner_sent + player_sent


async def send_debug_achievement_notification(bot, db, tournament_id: int, requester_tg_id: int) -> int:
    """Send only the requester's own persisted payload; never redirects other players' rows."""
    user = db.execute(select(models.User).where(models.User.tg_id == requester_tg_id)).scalar_one_or_none()
    if user is None or bot is None:
        return 0
    queued = (
        db.execute(
            select(models.AchievementReportDelivery)
            .where(
                models.AchievementReportDelivery.tournament_id == tournament_id,
                models.AchievementReportDelivery.recipient_type == RECIPIENT_PLAYER,
                models.AchievementReportDelivery.user_id == user.id,
            )
            .order_by(models.AchievementReportDelivery.message_index)
        )
        .scalars()
        .all()
    )
    payloads = [delivery.payload for delivery in queued]
    if not payloads:
        awards = (
            db.execute(
                select(models.UserAchievement).where(
                    models.UserAchievement.tournament_id == tournament_id,
                    models.UserAchievement.user_id == user.id,
                )
            )
            .scalars()
            .all()
        )
        events = (
            db.execute(
                select(models.AchievementProgressEvent).where(
                    models.AchievementProgressEvent.tournament_id == tournament_id,
                    models.AchievementProgressEvent.user_id == user.id,
                )
            )
            .scalars()
            .all()
        )
        if awards or events:
            lines = ["🏅 Debug: только ваши ачивки"]
            lines.extend(f"Открыто: {row.code}:{row.level} — {row.evidence or 'без evidence'}" for row in awards)
            lines.extend(
                f"Прогресс {row.code}: {row.before_value} → {row.after_value} — {row.evidence or 'без evidence'}"
                for row in events
            )
            payloads = ["\n".join(lines)]
    sent = 0
    for payload in payloads:
        await bot.send_message(chat_id=requester_tg_id, text=payload)
        sent += 1
    return sent
