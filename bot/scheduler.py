"""Планировщик автоматического создания турниров и импорта AetherHub по расписанию клубов."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from telegram.ext import Application, ContextTypes

from core import models
from core.config import Club, ClubSchedule, app_cfg, settings
from core.database import SessionLocal
from core.schemas import TournamentCreate
from services.aetherhub import fetch_tournament, find_todays_pauper_tournament
from services.aetherhub_import import AetherhubImportService
from services.tournament import TournamentService

logger = logging.getLogger(__name__)

DAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


# ---------------------------------------------------------------------------
# Club definitions
# ---------------------------------------------------------------------------


def get_clubs() -> list[Club]:
    """Returns the list of configured clubs."""
    clubs = [
        Club(
            name="Goldfish",
            chat_id=app_cfg.goldfish_chat_id or 0,
            aetherhub_url="https://aetherhub.com/User/GoldFish",
            title_prefix="🐠 ",
            schedules=[
                ClubSchedule(
                    weekday="thursday",
                    game_time="19:45",
                    create_time="03:10",
                    aetherhub_fetch_times=[
                        "20:00",
                        "20:30",
                        "21:00",
                        "21:30",
                        "22:00",
                        "22:30",
                        "23:00",
                        "23:30",
                        "00:00",
                        "00:30",
                    ],
                ),
                ClubSchedule(
                    weekday="friday",
                    game_time="19:45",
                    create_time="12:00",
                    aetherhub_fetch_times=[
                        "20:00",
                        "20:30",
                        "21:00",
                        "21:30",
                        "22:00",
                        "22:30",
                        "23:00",
                        "23:30",
                        "00:00",
                        "00:30",
                    ],
                ),
            ],
        ),
        Club(
            name="Edinorog",
            chat_id=app_cfg.edinorog_chat_id or 0,
            aetherhub_url="https://aetherhub.com/User/Edinorog/",
            title_prefix="🦄 ",
            schedules=[
                ClubSchedule(
                    weekday="monday",
                    game_time="19:30",
                    create_time="12:00",
                    aetherhub_fetch_times=[
                        "20:00",
                        "20:30",
                        "21:00",
                        "21:30",
                        "22:00",
                        "22:30",
                        "23:00",
                        "23:30",
                        "00:00",
                        "00:30",
                    ],
                ),
            ],
        ),
    ]
    if settings.DEBUG:
        clubs.append(
            Club(
                name="Debug",
                chat_id=app_cfg.goldfish_chat_id or 0,
                aetherhub_url="https://aetherhub.com/User/GoldFish",
                title_prefix="[DEBUG] 🐠 ",
                schedules=[
                    ClubSchedule(
                        weekday="thursday",
                        game_time="11:55",
                        create_time="11:55",
                        aetherhub_fetch_times=["11:56"],
                        find_latest=True,
                    )
                ],
            )
        )
    return clubs


# ---------------------------------------------------------------------------
# Job: create tournament
# ---------------------------------------------------------------------------


class CreateTournamentJob:
    """Creates the club's tournament on the scheduled weekday."""

    def __init__(self, club: Club, schedule: ClubSchedule) -> None:
        self.club = club
        self.schedule = schedule

    async def run(self, bot, now: datetime, db=None) -> None:
        if now.weekday() != DAYS[self.schedule.weekday]:
            logger.info(
                f"CreateTournamentJob: skipping '{self.club.name}' — not {self.schedule.weekday} (now={now.strftime('%A')})"
            )
            return

        date_str = now.strftime("%Y-%m-%d")
        title = f"{self.club.title_prefix}{self.club.name} Pauper {now.strftime('%d.%m.%Y')}"
        slug = f"{date_str}-{self.club.name.lower()}-pauper"

        close_db = db is None
        if close_db:
            db = SessionLocal()
        try:
            svc = TournamentService(db)
            try:
                active = svc.get_active_tournament_for_chat(self.club.chat_id or 0)
                if active:
                    svc.close_tournament(active.id)
                    logger.info(f"Closed previous tournament #{active.id} for '{self.club.name}'")

                new_t = svc.create_tournament(
                    TournamentCreate(
                        title=title,
                        chat_id=self.club.chat_id or 0,
                        slug=slug,
                        club=self.club.name,
                    )
                )
                logger.info(f"Created tournament #{new_t.id} '{title}' for '{self.club.name}'")

                if settings.ANNOUNCE_CHAT_ID and bot is not None:
                    await bot.send_message(
                        chat_id=settings.ANNOUNCE_CHAT_ID,
                        text=(
                            f"🏆 {self.club.name} Pauper — сегодня в {self.schedule.game_time}\n"
                            f"Турнир создан. Регистрация открыта."
                        ),
                    )
            except Exception as e:
                logger.error(f"CreateTournamentJob error for '{self.club.name}': {e}", exc_info=True)
        finally:
            if close_db:
                db.close()


# ---------------------------------------------------------------------------
# Job: AetherHub auto-import
# ---------------------------------------------------------------------------


class AetherhubImportJob:
    """Fetches today's pauper tournament from AetherHub and imports it automatically."""

    def __init__(self, club: Club, schedule: ClubSchedule) -> None:
        self.club = club
        self.schedule = schedule

    async def run(self, now: datetime, db=None) -> None:
        if not self.club.aetherhub_url:
            return
        if now.weekday() != DAYS[self.schedule.weekday]:
            logger.info(
                f"AetherhubImportJob: skipping '{self.club.name}' — not {self.schedule.weekday} (now={now.strftime('%A')})"
            )
            return

        close_db = db is None
        if close_db:
            db = SessionLocal()

        url: str | None = None
        tournament_id: int | None = None

        try:
            tournament = _find_active_club_tournament(db, self.club.name)
            if not tournament:
                logger.warning(f"AetherhubImportJob: no active tournament for '{self.club.name}'")
                return

            tournament_id = tournament.id
            url = tournament.aetherhub_url

            if not url:
                logger.info(f"AetherhubImportJob: fetching club page for '{self.club.name}'")
                today = None if self.schedule.find_latest else now.date()
                try:
                    url = find_todays_pauper_tournament(self.club.aetherhub_url, today=today)
                except Exception:
                    logger.exception(f"AetherhubImportJob: failed to fetch club page for '{self.club.name}'")
                    return
                if not url:
                    logger.info(f"AetherhubImportJob: no pauper tournament found for '{self.club.name}'")
                    return

            logger.info(f"AetherhubImportJob: importing {url} for tournament #{tournament_id}")
            try:
                data = fetch_tournament(url)
            except Exception:
                logger.exception(f"AetherhubImportJob: failed to fetch tournament data from {url}")
                return

            try:
                result = AetherhubImportService(db).import_tournament(tournament_id, data)
                logger.info(
                    f"AetherhubImportJob done for '{self.club.name}' #{tournament_id}: "
                    f"registered={result.registered}, already={result.already_registered}, "
                    f"pairings={result.pairings_saved}"
                )
            except Exception:
                logger.exception(f"AetherhubImportJob: import failed for '{self.club.name}'")
                return
        finally:
            if close_db:
                db.close()

        if tournament_id and url:
            db2 = SessionLocal()
            try:
                TournamentService(db2).set_aetherhub_url(tournament_id, url)
            except Exception:
                logger.exception(f"AetherhubImportJob: failed to save aetherhub_url for #{tournament_id}")
            finally:
                db2.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_active_club_tournament(db, club_name: str):
    """Find the current non-CLOSED tournament for a club."""
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


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def setup_scheduler(app: Application) -> None:
    """Registers daily jobs for each club and schedule."""
    tz = ZoneInfo(settings.TOURNAMENT_TIMEZONE)

    for club in get_clubs():
        for schedule in club.schedules:
            time_str = schedule.create_time or settings.TOURNAMENT_CREATE_TIME
            create_time = datetime.strptime(time_str, "%H:%M").time().replace(tzinfo=tz)

            create_job = CreateTournamentJob(club, schedule)

            async def _create(context: ContextTypes.DEFAULT_TYPE, _job=create_job) -> None:
                tz_ = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
                await _job.run(bot=context.bot, now=datetime.now(tz_))

            _create.__name__ = f"create_tournament[{club.name}/{schedule.weekday}]"
            app.job_queue.run_daily(_create, time=create_time, days=(DAYS[schedule.weekday],))
            logger.info(
                f"Scheduler: {club.name} create on {schedule.weekday} at {time_str} "
                f"({settings.TOURNAMENT_TIMEZONE}), game at {schedule.game_time}"
            )

            for fetch_time_str in schedule.aetherhub_fetch_times:
                fetch_time = datetime.strptime(fetch_time_str, "%H:%M").time().replace(tzinfo=tz)
                import_job = AetherhubImportJob(club, schedule)

                async def _import(context: ContextTypes.DEFAULT_TYPE, _job=import_job) -> None:
                    tz_ = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
                    await _job.run(now=datetime.now(tz_))

                _import.__name__ = f"aetherhub_import[{club.name}/{schedule.weekday}/{fetch_time_str}]"
                app.job_queue.run_daily(_import, time=fetch_time, days=(DAYS[schedule.weekday],))
                logger.info(f"Scheduler: AetherHub import for '{club.name}' ({schedule.weekday}) at {fetch_time_str}")


_DAY_RU = {
    "monday": "понедельник",
    "tuesday": "вторник",
    "wednesday": "среда",
    "thursday": "четверг",
    "friday": "пятница",
    "saturday": "суббота",
    "sunday": "воскресенье",
}


def _format_club_schedule(club: Club) -> str:
    lines = [f"\n{club.title_prefix}{club.name}:"]
    for schedule in club.schedules:
        time_str = schedule.create_time or settings.TOURNAMENT_CREATE_TIME
        day_ru = _DAY_RU.get(schedule.weekday.lower(), schedule.weekday)
        lines.append(f"  {day_ru}: создание {time_str}, игра {schedule.game_time}")
        if schedule.aetherhub_fetch_times:
            lines.append(f"    импорт: {', '.join(schedule.aetherhub_fetch_times)}")
    return "\n".join(lines)


def format_schedule_text() -> str:
    """Возвращает текстовое описание расписания для команды /schedule."""
    tz = settings.TOURNAMENT_TIMEZONE
    lines = [f"📅 Расписание ({tz}):"]
    for club in get_clubs():
        lines.append(_format_club_schedule(club))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Legacy helpers — used in old scheduler tests
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
