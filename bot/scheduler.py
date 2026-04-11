"""Планировщик автоматического создания турниров по расписанию."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram.ext import Application, ContextTypes

from core.config import settings
from core.database import SessionLocal
from core.schemas import TournamentCreate
from services.tournament import TournamentService

logger = logging.getLogger(__name__)

DAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def parse_schedule(schedule_str: str) -> tuple[int, datetime.time]:
    """Парсит строку "friday 19:00" в (weekday_int, time)."""
    parts = schedule_str.lower().split()
    if len(parts) != 2:
        raise ValueError(f"Invalid TOURNAMENT_SCHEDULE format: '{schedule_str}'. Expected 'weekday HH:MM'")
    day_str, time_str = parts
    if day_str not in DAYS:
        raise ValueError(f"Unknown weekday: '{day_str}'")
    weekday = DAYS[day_str]
    t = datetime.strptime(time_str, "%H:%M").time()
    return weekday, t


async def _create_tournaments_for_schedule(bot, schedule_entry: str) -> None:
    """Создаёт турниры для одной записи расписания, если сегодня нужный день."""
    tz = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
    now = datetime.now(tz)
    target_weekday, _ = parse_schedule(schedule_entry)

    logger.info(
        f"Job fired for '{schedule_entry}': now={now.strftime('%A %H:%M')} "
        f"(weekday={now.weekday()}), target_weekday={target_weekday}"
    )

    if now.weekday() != target_weekday:
        logger.info("Not the right weekday, skipping.")
        return

    chat_ids = settings.chat_ids
    logger.info(f"Target chat_ids: {chat_ids}")

    if not chat_ids:
        logger.warning("TOURNAMENT_CHAT_IDS is empty — no tournaments will be created")
        return

    date_str = now.strftime("%Y-%m-%d")
    title = f"Pauper {date_str}"
    slug = f"{date_str}-pauper"

    db = SessionLocal()
    try:
        svc = TournamentService(db)
        for chat_id in chat_ids:
            try:
                logger.info(f"Processing chat {chat_id}...")
                active = svc.get_active_tournament_for_chat(chat_id)
                if active:
                    svc.close_tournament(active.id)
                    logger.info(f"Closed previous tournament #{active.id} for chat {chat_id}")

                new_t = svc.create_tournament(TournamentCreate(
                    title=title,
                    chat_id=chat_id,
                    slug=slug,
                ))
                logger.info(f"Created tournament #{new_t.id} '{title}' for chat {chat_id}")

                await bot.send_message(
                    chat_id=chat_id,
                    text=f"🏆 Новый турнир: {title}\nРегистрация открыта! Используйте /tournaments для записи.",
                )
                logger.info(f"Announcement sent to chat {chat_id}")
            except Exception as e:
                logger.error(f"Scheduler error for chat {chat_id}: {e}", exc_info=True)
    finally:
        db.close()


def _make_job(schedule_entry: str):
    async def job(context: ContextTypes.DEFAULT_TYPE) -> None:
        await _create_tournaments_for_schedule(context.bot, schedule_entry)
    job.__name__ = f"scheduled_tournament_job[{schedule_entry}]"
    return job


def setup_scheduler(app: Application) -> None:
    """Регистрирует джобы по расписанию из конфига (один джоб на каждую запись)."""
    tz = ZoneInfo(settings.TOURNAMENT_TIMEZONE)

    for schedule_entry in settings.schedule_list:
        _, scheduled_time = parse_schedule(schedule_entry)
        aware_time = scheduled_time.replace(tzinfo=tz)
        app.job_queue.run_daily(_make_job(schedule_entry), time=aware_time)
        logger.info(
            f"Scheduler set up: tournaments created every {schedule_entry} "
            f"({settings.TOURNAMENT_TIMEZONE}) for chats: {settings.chat_ids}"
        )
