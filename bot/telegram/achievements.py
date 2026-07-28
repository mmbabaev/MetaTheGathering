"""Telegram-слой ачивок: команда /achievements и доставка отчёта.

Маршрутизация получателя — единственное место, где решается, кому уходят ачивки.
Пока флаг ``achievementsPlayerDm`` выключен, адресат ровно один: владелец
(``settings.OWNER_CHAT_ID``). Именно здесь произойдёт переключение на самих игроков,
и оно требует явного подтверждения владельца — это новый путь массовой рассылки DM
(см. CLAUDE.md «Notification safety» и docs/achievements.md §6).
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.features import FeatureService
from bot.handlers.achievements import AchievementsHandler
from core.config import settings
from core.database import SessionLocal
from services.achievements import AchievementService, build_report
from services.feature_flags import FeatureFlagService
from services.user import UserService

logger = logging.getLogger(__name__)


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
        result = _handler(db).handle_achievements(tg_id=user.id, query=query)
        await msg.reply_text(result.text)
    finally:
        db.close()


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
    result = service.process_tournament(tournament_id)
    if result is None:
        return 0

    messages = build_report(result)
    if not messages:
        logger.info("[achievements] tournament #%s: nothing new", tournament_id)
        return 0

    if features.are_achievement_dms_enabled():
        # Путь «уведомления игрокам» ещё не реализован (фаза 5). Пока флаг включён по ошибке —
        # не рассылаем ничего, а сообщаем владельцу: молча слать всем игрокам недопустимо.
        logger.warning("[achievements] player DMs are flagged on, but not implemented yet — falling back to owner")

    chat_id = settings.OWNER_CHAT_ID
    if not chat_id:
        logger.warning("[achievements] OWNER_CHAT_ID is not set — report not sent")
        return 0

    sent = 0
    for text in messages:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            sent += 1
        except Exception:  # noqa: BLE001 — отчёт не должен ронять завершение турнира
            logger.exception("[achievements] could not send report for #%s", tournament_id)
            return sent

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
