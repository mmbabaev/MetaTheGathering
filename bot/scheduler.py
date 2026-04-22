"""Планировщик автоматического создания турниров по расписанию клубов."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram.ext import Application, ContextTypes

from core.config import settings, ClubConfig
from core.database import SessionLocal
from core.schemas import TournamentCreate
from core import models
from services.tournament import TournamentService
from services.aetherhub_import import AetherhubImportService
from services.aetherhub import fetch_tournament, find_todays_pauper_tournament

logger = logging.getLogger(__name__)

DAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# ---------------------------------------------------------------------------
# Расписание клубов — бизнес-логика, хранится в коде
# chat_id задаётся в .env (GOLDFISH_CHAT_ID / EDINOROG_CHAT_ID)
# ---------------------------------------------------------------------------

def get_clubs() -> list[ClubConfig]:
    """Возвращает список клубов. chat_id=0 означает «создать турнир, но не писать в чат»."""
    clubs = [
        ClubConfig(
            name="Goldfish",
            weekday="thursday",
            chat_id=settings.GOLDFISH_CHAT_ID or 0,
            game_time="19:30",
            aetherhub_url="https://aetherhub.com/User/GoldFish",
            aetherhub_fetch_times=["21:00", "22:00", "23:00"],
        ),
        ClubConfig(
            name="Edinorog",
            weekday="monday",
            chat_id=settings.EDINOROG_CHAT_ID or 0,
            game_time="19:30",
            create_time="12:00",
            title_prefix="🦄 ",
        ),
    ]
    if settings.DEBUG:
        clubs.append(
            ClubConfig(name="Debug", weekday="saturday", chat_id=settings.GOLDFISH_CHAT_ID or 0, game_time="14:20")
        )
    return clubs


# ---------------------------------------------------------------------------
# Создание турнира для клуба
# ---------------------------------------------------------------------------

async def _create_club_tournament(bot, club: ClubConfig) -> None:
    """Создаёт турнир для клуба, если сегодня нужный день."""
    tz = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
    now = datetime.now(tz)
    target_weekday = DAYS.get(club.weekday.lower())

    if target_weekday is None:
        logger.error(f"Unknown weekday '{club.weekday}' for club '{club.name}'")
        return

    logger.info(
        f"Club job fired for '{club.name}': now={now.strftime('%A %H:%M')} "
        f"(weekday={now.weekday()}), target={target_weekday}"
    )

    if now.weekday() != target_weekday:
        logger.info("Not the right weekday, skipping.")
        return

    date_str = now.strftime("%Y-%m-%d")
    title = f"{club.title_prefix}{club.name} Pauper {date_str}"
    slug = f"{date_str}-{club.name.lower()}-pauper"

    db = SessionLocal()
    try:
        svc = TournamentService(db)
        try:
            active = svc.get_active_tournament_for_chat(club.chat_id or 0)
            if active:
                svc.close_tournament(active.id)
                logger.info(f"Closed previous tournament #{active.id} for club '{club.name}'")

            new_t = svc.create_tournament(TournamentCreate(
                title=title,
                chat_id=club.chat_id or 0,
                slug=slug,
                club=club.name,
            ))
            logger.info(f"Created tournament #{new_t.id} '{title}' for club '{club.name}'")

            if club.chat_id:
                await bot.send_message(
                    chat_id=club.chat_id,
                    text=(
                        f"🏆 {club.name} Pauper — сегодня в {club.game_time}\n"
                        f"Регистрация открыта! Используйте /tournaments для записи."
                    ),
                )
                logger.info(f"Announcement sent to chat {club.chat_id}")
            else:
                logger.info(f"No chat_id for '{club.name}' — tournament created without announcement")
        except Exception as e:
            logger.error(f"Scheduler error for club '{club.name}': {e}", exc_info=True)
    finally:
        db.close()


def _find_active_club_tournament(db, club_name: str):
    """Find the current non-CLOSED tournament for a club."""
    from sqlalchemy import select
    stmt = (
        select(models.Tournament)
        .where(
            models.Tournament.club == club_name,
            models.Tournament.status != models.TournamentStatus.CLOSED,
        )
        .order_by(models.Tournament.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


async def _aetherhub_auto_import(club: ClubConfig) -> None:
    """Fetch today's pauper tournament from AetherHub and import it automatically."""
    if not club.aetherhub_url:
        return

    tz = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
    now = datetime.now(tz)
    target_weekday = DAYS.get(club.weekday.lower())

    if target_weekday is None or now.weekday() != target_weekday:
        logger.info(f"AetherHub import: not the right weekday for '{club.name}', skipping.")
        return

    db = SessionLocal()
    try:
        tournament = _find_active_club_tournament(db, club.name)
        if not tournament:
            logger.warning(f"AetherHub import: no active tournament for club '{club.name}'")
            return

        url = tournament.aetherhub_url
        if not url:
            logger.info(f"AetherHub import: fetching club page for '{club.name}'")
            try:
                url = find_todays_pauper_tournament(club.aetherhub_url, today=now.date())
            except Exception:
                logger.exception(f"AetherHub import: failed to fetch club page for '{club.name}'")
                return
            if not url:
                logger.info(f"AetherHub import: no pauper tournament found today for '{club.name}'")
                return

        logger.info(f"AetherHub import: importing {url} for tournament #{tournament.id}")
        try:
            data = fetch_tournament(url)
        except Exception:
            logger.exception(f"AetherHub import: failed to fetch tournament data from {url}")
            return

        try:
            result = AetherhubImportService(db).import_tournament(tournament.id, data)
            logger.info(
                f"AetherHub import done for '{club.name}' #{tournament.id}: "
                f"registered={result.registered}, already={result.already_registered}, "
                f"pairings={result.pairings_saved}"
            )
        except Exception:
            logger.exception(f"AetherHub import: import_tournament failed for '{club.name}'")
            return
    finally:
        db.close()

    db2 = SessionLocal()
    try:
        TournamentService(db2).set_aetherhub_url(tournament.id, url)
    except Exception:
        logger.exception(f"AetherHub import: failed to save aetherhub_url for tournament #{tournament.id}")
    finally:
        db2.close()


def _make_aetherhub_job(club: ClubConfig):
    async def job(context: ContextTypes.DEFAULT_TYPE) -> None:
        await _aetherhub_auto_import(club)
    job.__name__ = f"aetherhub_import_job[{club.name}]"
    return job


def _make_club_job(club: ClubConfig):
    async def job(context: ContextTypes.DEFAULT_TYPE) -> None:
        await _create_club_tournament(context.bot, club)
    job.__name__ = f"club_tournament_job[{club.name}]"
    return job


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_scheduler(app: Application) -> None:
    """Регистрирует ежедневные джобы для каждого клуба."""
    tz = ZoneInfo(settings.TOURNAMENT_TIMEZONE)

    clubs = get_clubs()
    for club in clubs:
        time_str = club.create_time or settings.TOURNAMENT_CREATE_TIME
        create_time = datetime.strptime(time_str, "%H:%M").time()
        aware_create_time = create_time.replace(tzinfo=tz)
        app.job_queue.run_daily(_make_club_job(club), time=aware_create_time)
        logger.info(
            f"Scheduler: {club.name} every {club.weekday} at {time_str} "
            f"({settings.TOURNAMENT_TIMEZONE}), game at {club.game_time}, chat={club.chat_id}"
        )

        for fetch_time_str in club.aetherhub_fetch_times:
            fetch_time = datetime.strptime(fetch_time_str, "%H:%M").time().replace(tzinfo=tz)
            app.job_queue.run_daily(_make_aetherhub_job(club), time=fetch_time)
            logger.info(
                f"Scheduler: AetherHub import for '{club.name}' at {fetch_time_str} ({settings.TOURNAMENT_TIMEZONE})"
            )


# ---------------------------------------------------------------------------
# Legacy helpers — используются в тестах планировщика
# ---------------------------------------------------------------------------

def parse_schedule(schedule_str: str) -> tuple[int, datetime.time]:
    """Парсит строку "friday 19:00" в (weekday_int, time)."""
    parts = schedule_str.lower().split()
    if len(parts) != 2:
        raise ValueError(f"Invalid schedule format: '{schedule_str}'. Expected 'weekday HH:MM'")
    day_str, time_str = parts
    if day_str not in DAYS:
        raise ValueError(f"Unknown weekday: '{day_str}'")
    return DAYS[day_str], datetime.strptime(time_str, "%H:%M").time()


async def _create_tournaments_for_schedule(bot, schedule_entry: str) -> None:
    """Legacy: создаёт турниры по расписанию для списка chat_ids (используется в тестах)."""
    tz = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
    now = datetime.now(tz)
    target_weekday, _ = parse_schedule(schedule_entry)

    logger.info(
        f"Legacy job fired for '{schedule_entry}': now={now.strftime('%A %H:%M')} "
        f"(weekday={now.weekday()}), target_weekday={target_weekday}"
    )

    if now.weekday() != target_weekday:
        logger.info("Not the right weekday, skipping.")
        return

    chat_ids = settings.chat_ids
    if not chat_ids:
        logger.warning("No chat_ids configured — skipping")
        return

    date_str = now.strftime("%Y-%m-%d")
    title = f"Pauper {date_str}"
    slug = f"{date_str}-pauper"

    db = SessionLocal()
    try:
        svc = TournamentService(db)
        for chat_id in chat_ids:
            try:
                active = svc.get_active_tournament_for_chat(chat_id)
                if active:
                    svc.close_tournament(active.id)
                new_t = svc.create_tournament(TournamentCreate(title=title, chat_id=chat_id, slug=slug))
                logger.info(f"Created tournament #{new_t.id} for chat {chat_id}")
                await bot.send_message(chat_id=chat_id, text=f"🏆 Новый турнир: {title}\nРегистрация открыта! /tournaments")
            except Exception as e:
                logger.error(f"Error for chat {chat_id}: {e}", exc_info=True)
    finally:
        db.close()


def _make_job(schedule_entry: str):
    async def job(context: ContextTypes.DEFAULT_TYPE) -> None:
        await _create_tournaments_for_schedule(context.bot, schedule_entry)
    job.__name__ = f"scheduled_tournament_job[{schedule_entry}]"
    return job
